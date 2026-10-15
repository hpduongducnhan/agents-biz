/** Cầu RabbitMQ của 1 instance: queue exclusive riêng + binding động; tự nối lại và khai lại binding. */

import { randomBytes } from "node:crypto";
import { hostname } from "node:os";

import { type Channel, type ChannelModel, connect } from "amqplib";

import { BindingSync } from "./bindings.ts";
import { RT_IN, RT_OUT, RT_UNROUTED } from "./envelope.ts";
import type { Logger } from "./log.ts";

export interface Delivery {
  routingKey: string;
  body: Buffer;
  correlationId?: string;
}

export interface BridgeOptions {
  queueMax: number;
  messageTtlMs: number;
}

export class RabbitBridge {
  private readonly url: string;
  private readonly log: Logger;
  private readonly opts: BridgeOptions;
  private readonly bindings: BindingSync;
  private conn: ChannelModel | null = null;
  private ch: Channel | null = null;
  private onDelivery: (d: Delivery) => void = () => {};
  private closed = false;
  queue = "";
  connected = false;

  constructor(url: string, log: Logger, opts: BridgeOptions, currentKeys: () => string[]) {
    this.url = url;
    this.log = log;
    this.opts = opts;
    this.bindings = new BindingSync(() => ["all", ...currentKeys()], (op, key) => this.binding(op, key));
  }

  /** Key đã bind THẬT trên queue hiện tại (không tính `all`). */
  boundKeys(): string[] {
    return this.bindings.keys().filter((k) => k !== "all");
  }

  /** Bảng key vừa đổi → đồng bộ binding (tuần tự, không bao giờ ném). */
  sync(): Promise<void> {
    return this.bindings.sync();
  }

  async start(onDelivery: (d: Delivery) => void): Promise<void> {
    this.onDelivery = onDelivery;
    await this.connectOnce();
  }

  private async connectOnce(): Promise<void> {
    const conn = await connect(this.url);
    const ch = await conn.createChannel();
    // Khai GIỐNG HỆT backend — khác tham số là RabbitMQ từ chối (PRECONDITION_FAILED).
    await ch.assertExchange(RT_OUT, "topic", { durable: true });
    await ch.assertExchange(RT_IN, "topic", { durable: true, arguments: { "alternate-exchange": RT_UNROUTED } });
    await ch.assertExchange(RT_UNROUTED, "fanout", { durable: true });
    const name = `bw.rt.instance.${hostname().replace(/[^A-Za-z0-9_-]/g, "-")}.${randomBytes(3).toString("hex")}`;
    const q = await ch.assertQueue(name, {
      exclusive: true,
      autoDelete: true,
      arguments: {
        "x-message-ttl": this.opts.messageTtlMs,
        "x-max-length": this.opts.queueMax,
        "x-overflow": "drop-head",
      },
    });
    await ch.consume(
      q.queue,
      (msg) => {
        if (msg) {
          this.onDelivery({
            routingKey: msg.fields.routingKey,
            body: msg.content,
            correlationId: msg.properties.correlationId,
          });
        }
      },
      { noAck: true },
    );
    conn.on("error", (err: Error) => this.log.warn(`lỗi kết nối RabbitMQ: ${err.message}`, { loc: "ws2502" }));
    conn.on("close", () => this.onClose());
    ch.on("error", (err: Error) => this.log.warn(`RabbitMQ đóng kênh: ${err.message}`, { loc: "ws2506" }));
    ch.on("close", () => {
      if (this.ch !== ch) return;
      // Kênh chết mà kết nối còn sống: không nhận / gửi được nữa → đóng kết nối để nối lại từ đầu.
      this.ch = null;
      this.connected = false;
      conn.close().catch(() => undefined);
    });
    this.conn = conn;
    this.ch = ch;
    this.queue = q.queue;
    this.bindings.reset(); // queue mới: bind lại `all` + mọi key đang có socket
    await this.bindings.sync();
    this.connected = this.ch === ch; // health xanh khi binding đã về (kênh không chết giữa chừng)
    this.log.info("đã kết nối RabbitMQ", { loc: "ws2101", queue: q.queue, bindings: this.bindings.keys().length });
  }

  private onClose(): void {
    this.connected = false;
    this.ch = null;
    this.conn = null;
    if (this.closed) return;
    this.log.warn("mất kết nối RabbitMQ — sẽ nối lại", { loc: "ws2501" });
    this.reconnect(500);
  }

  private reconnect(delayMs: number): void {
    setTimeout(async () => {
      if (this.closed) return;
      try {
        await this.connectOnce();
      } catch (err) {
        this.log.warn(`nối lại RabbitMQ lỗi: ${(err as Error).message}`, { loc: "ws2503", retry_ms: delayMs });
        this.reconnect(Math.min(delayMs * 2, 10_000));
      }
    }, delayMs).unref();
  }

  /** Mất kết nối lúc bind / unbind: không sao — lần nối lại sẽ bind đúng tập key hiện tại. Không bao giờ ném
   * (promise bị từ chối không ai bắt = Node dừng process). */
  private async binding(op: "bind" | "unbind", key: string): Promise<boolean> {
    const ch = this.ch;
    if (!ch || this.closed) return false;
    try {
      if (op === "bind") await ch.bindQueue(this.queue, RT_OUT, key);
      else await ch.unbindQueue(this.queue, RT_OUT, key);
      return true;
    } catch (err) {
      if (!this.closed) this.log.warn(`${op} ${key} lỗi: ${(err as Error).message}`, { loc: "ws2504" });
      return false;
    }
  }

  /** false = chưa có kết nối (không gửi). `publish()` của amqplib trả false khi bộ đệm ghi đầy nhưng message VẪN
   * được xếp để gửi — coi đó là thất bại sẽ khiến client gửi lại và backend nhận trùng. */
  publishIn(routingKey: string, envelope: unknown, cid: string): boolean {
    const ch = this.ch;
    if (!ch || !this.connected) return false;
    try {
      ch.publish(RT_IN, routingKey, Buffer.from(JSON.stringify(envelope)), {
        persistent: true,
        correlationId: cid,
        contentType: "application/json",
      });
      return true;
    } catch (err) {
      this.log.warn(`gửi bw.rt.in lỗi: ${(err as Error).message}`, { loc: "ws2506", routing_key: routingKey, cid });
      return false;
    }
  }

  /** Test: làm rớt kết nối như sự cố mạng (không đánh dấu đóng → sẽ tự nối lại). */
  async dropForTest(): Promise<void> {
    await this.conn?.close();
  }

  async close(): Promise<void> {
    this.closed = true;
    await this.conn?.close().catch(() => undefined);
  }
}
