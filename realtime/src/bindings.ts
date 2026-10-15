/** Đếm socket theo routing key: socket ĐẦU TIÊN cần key → bind; socket CUỐI CÙNG rời → unbind. */

export class BindingTable {
  private counts = new Map<string, number>();

  acquire(keys: string[]): string[] {
    const fresh: string[] = [];
    for (const key of keys) {
      const n = (this.counts.get(key) ?? 0) + 1;
      this.counts.set(key, n);
      if (n === 1) fresh.push(key);
    }
    return fresh;
  }

  release(keys: string[]): string[] {
    const gone: string[] = [];
    for (const key of keys) {
      const n = this.counts.get(key);
      if (n === undefined) continue;
      if (n <= 1) {
        this.counts.delete(key);
        gone.push(key);
      } else {
        this.counts.set(key, n - 1);
      }
    }
    return gone;
  }

  keys(): string[] {
    return [...this.counts.keys()];
  }

  get size(): number {
    return this.counts.size;
  }
}

type Op = "bind" | "unbind";

/**
 * Đồng bộ binding THẬT trên RabbitMQ với tập key cần có: một vòng tuần tự chạy tới khi khớp, nên socket nối / rời
 * xen giữa lúc RPC đang bay không làm lệch. `reset()` khi có queue mới (nối lại) — bind lại từ đầu, bỏ qua trả lời
 * của kênh cũ.
 */
export class BindingSync {
  private readonly want: () => Iterable<string>;
  private readonly apply: (op: Op, key: string) => Promise<boolean>;
  private bound = new Set<string>();
  private generation = 0;
  private dirty = false;
  private running: Promise<void> | null = null;

  constructor(want: () => Iterable<string>, apply: (op: Op, key: string) => Promise<boolean>) {
    this.want = want;
    this.apply = apply;
  }

  keys(): string[] {
    return [...this.bound];
  }

  reset(): void {
    this.generation++;
    this.bound = new Set();
    void this.sync();
  }

  /** Không bao giờ ném; promise xong khi vòng đồng bộ đang chạy (gồm yêu cầu này) dừng. */
  sync(): Promise<void> {
    this.dirty = true;
    this.running ??= Promise.resolve().then(() => this.loop());
    return this.running;
  }

  private async loop(): Promise<void> {
    try {
      while (this.dirty) {
        this.dirty = false;
        const generation = this.generation;
        const want = new Set(this.want());
        const todo: Array<[Op, string]> = [
          ...[...want].filter((k) => !this.bound.has(k)).map((k): [Op, string] => ["bind", k]),
          ...[...this.bound].filter((k) => !want.has(k)).map((k): [Op, string] => ["unbind", k]),
        ];
        for (const [op, key] of todo) {
          const ok = await this.apply(op, key);
          if (generation !== this.generation) {
            this.dirty = true; // queue mới trong lúc chờ → làm lại từ đầu
            break;
          }
          if (!ok) return; // mất kênh: reset() lúc nối lại sẽ đồng bộ lại
          if (op === "bind") this.bound.add(key);
          else this.bound.delete(key);
        }
      }
    } finally {
      this.running = null;
    }
  }
}
