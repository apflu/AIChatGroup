"""DeliveryQueue：单消费者队列的入队 / 出队 / 抢占（beat 戳），以及 perform_queue 的丢弃语义。"""
import asyncio

from aichatgroup.domain import Agent, RoomState
from aichatgroup.io.transport import InMemoryTransport
from aichatgroup.message.delivery import DeliveryQueue, perform_queue
from aichatgroup.message.generator.parsing import parse_turn_output


def _agent():
    return Agent(id="a1", name="小丸子", model_id="m")


def _bubbles(n: int):
    return parse_turn_output("{{SEPARATOR}}".join(f"第{i}句" for i in range(n)))[0]


def test_push_pop_in_order_and_done_clears_in_flight():
    q = DeliveryQueue()
    assert q.push(_agent(), _bubbles(2), [0.0, 0.5], beat=q.beat)
    assert len(q) == 2 and not q.idle
    a = q.pop()
    assert a.bubble.text == "第0句" and a.pause == 0.0 and not q.is_stale(a)
    q.done(a)
    b = q.pop()
    assert b.bubble.text == "第1句" and b.pause == 0.5
    q.done(b)
    assert q.pop() is None and q.idle


def test_abort_drops_pending_and_stales_in_flight():
    q = DeliveryQueue()
    q.push(_agent(), _bubbles(3), [0.0, 0.1, 0.1], beat=q.beat)
    first = q.pop()                       # 正在等节奏的那条
    dropped = q.abort(reason="test")
    assert dropped == 3                   # 2 pending + 1 in-flight
    assert len(q) == 0 and q.is_stale(first) and q.beat == 1 and q.aborts == 1


def test_push_with_stale_beat_is_discarded():
    # 生成期间被抢占：生成回来后拿着旧戳入队 → 整批作废
    q = DeliveryQueue()
    stamp = q.beat
    q.abort()
    assert q.push(_agent(), _bubbles(2), [0.0, 0.1], beat=stamp) is False
    assert len(q) == 0


def test_perform_queue_stops_at_abort_and_trails_off():
    # 第 2 条在等节奏时被抢占：只发出第 1 条，第 2、3 条不发不回调，旁白补一句收尾
    q = DeliveryQueue()
    agent = _agent()
    q.push(agent, _bubbles(3), [0.0, 0.2, 0.2], beat=q.beat)
    tr = InMemoryTransport()
    seen = []

    async def sleep(s):
        q.abort(reason="user")            # 抢占恰好落在 typing 等待期间
        await asyncio.sleep(0)

    sent = asyncio.run(perform_queue(tr, q, RoomState(), sleep=sleep, on_sent=lambda pb, ext: seen.append(pb.text)))
    assert sent == 1
    assert [t for _, t in tr.sent] == ["第0句"]
    assert seen == ["第0句"]
    assert tr.system_sent == ["小丸子的话说到一半，停住了。"]
    assert q.idle


def test_perform_queue_no_trail_off_when_nothing_was_said():
    # 首条就被抢占（还没开口）：什么都不发，也不补旁白
    q = DeliveryQueue()
    q.push(_agent(), _bubbles(2), [0.0, 0.2], beat=q.beat)
    tr = InMemoryTransport()

    async def sleep(s):
        await asyncio.sleep(0)

    q.abort()
    sent = asyncio.run(perform_queue(tr, q, RoomState(), sleep=sleep, on_sent=lambda pb, ext: None))
    assert sent == 0 and tr.sent == [] and tr.system_sent == []
