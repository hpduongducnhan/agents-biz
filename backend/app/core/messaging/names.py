"""Tên exchange / queue cố định của lõi + factory khai báo (mọi nơi khai giống hệt nhau)."""

from __future__ import annotations

from faststream.rabbit import ExchangeType, QueueType, RabbitExchange, RabbitQueue

BCAST_EXCHANGE = "bw.sys.bcast"
RT_OUT_EXCHANGE = "bw.rt.out"
RT_IN_EXCHANGE = "bw.rt.in"
RT_UNROUTED_EXCHANGE = "bw.rt.in.unrouted"
RT_UNROUTED_QUEUE = "bw.rt.in.unrouted"
TQ_EXCHANGE = "bw.tq"
TQ_DEAD_LETTER = "bw.tq.dead_letter"
TQ_DEFAULT_QUEUE = "bw.tq.default"


def bcast_exchange() -> RabbitExchange:
    return RabbitExchange(BCAST_EXCHANGE, type=ExchangeType.TOPIC, durable=True)


def rt_out_exchange() -> RabbitExchange:
    return RabbitExchange(RT_OUT_EXCHANGE, type=ExchangeType.TOPIC, durable=True)


def rt_in_exchange() -> RabbitExchange:
    """Service realtime (Node) khai CÙNG tham số (khác tham số → RabbitMQ từ chối khai)."""
    return RabbitExchange(
        RT_IN_EXCHANGE, type=ExchangeType.TOPIC, durable=True, arguments={"alternate-exchange": RT_UNROUTED_EXCHANGE}
    )


def rt_unrouted_exchange() -> RabbitExchange:
    return RabbitExchange(RT_UNROUTED_EXCHANGE, type=ExchangeType.FANOUT, durable=True)


def dlq_name(queue: str) -> str:
    return f"{queue}.dlq"


def work_queue(name: str, *, dlq: bool = False, routing_key: str = "") -> RabbitQueue:
    """Queue bền (quorum). `dlq` → message bị reject đi `<name>.dlq` qua default exchange.
    Tham số queue không đổi được sau khi tạo: bật / tắt dlq cho queue đã có phải xoá queue."""
    arguments = {"x-dead-letter-exchange": "", "x-dead-letter-routing-key": dlq_name(name)} if dlq else None
    return RabbitQueue(name, queue_type=QueueType.QUORUM, durable=True, arguments=arguments, routing_key=routing_key)


def dlq_queue(name: str) -> RabbitQueue:
    return RabbitQueue(dlq_name(name), queue_type=QueueType.QUORUM, durable=True)
