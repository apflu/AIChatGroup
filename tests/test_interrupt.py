"""用户打断（抢占）：usher escalate 时清掉当前 beat 未发的气泡，在飞的生成作废，下一拍回应用户。

docs/message-ordering.md §7：附和 → 不抢占；关键打断 → 清 pending + beat_aborted + 立即重规划。
"""
import asyncio

from loguru import logger

from aichatgroup.domain import Agent, WorldBook
from aichatgroup.domain.types import GatewayResponse, Usage
from aichatgroup.io.gateway import MockGateway
from aichatgroup.io.persistence import Store
from aichatgroup.io.transport import InboundMessage, InMemoryTransport
from aichatgroup.message.conductor import RoundRobinConductor
from aichatgroup.message.usher import Usher
from aichatgroup.runtime import Orchestrator


class KeywordUsherGateway:
    """含"打断"的输入 → escalate(disrupt)，否则 absorb。"""

    def complete(self, system, messages, model_id, max_tokens=1024):
        text = messages[-1]["content"]
        return GatewayResponse(text="disrupt" if "打断" in text else "absorb", usage=Usage())


class _Events:
    def __init__(self):
        self.records = []
        self._id = None

    def __enter__(self):
        self._id = logger.add(lambda m: self.records.append(m.record), level="TRACE", format="{message}")
        return self

    def __exit__(self, *a):
        logger.remove(self._id)

    def of(self, kind):
        return [r["extra"] for r in self.records if r["extra"].get("event") == kind]


def _world():
    return WorldBook(bible="热闹的酒馆世界。" * 3, rules="遵守世界书。" * 3)


def _agents():
    return [
        Agent(id="a1", name="小丸子", model_id="m1", base_prompt="活泼。"),
        Agent(id="a2", name="阿福", model_id="m2", base_prompt="沉稳。"),
    ]


def _gateway():
    gw = MockGateway()
    gw.push_script("小丸子", ["第一句{{SEPARATOR}}第二句{{SEPARATOR}}第三句", "后来呢"])
    gw.push_script("阿福", ["你说什么？", "慢品。"])
    return gw


def _orch(gateway=None, sleep=None, store=None):
    async def _fast(_s):
        await asyncio.sleep(0)

    return Orchestrator(
        world=_world(), agents=_agents(), gateway=gateway or _gateway(),
        conductor=RoundRobinConductor(), transport=InMemoryTransport(),
        usher=Usher(KeywordUsherGateway(), model_id="haiku"),
        store=store, turn_interval_s=0.0, idle_poll_s=0.0, sleep=sleep or _fast,
    )


def _interrupting_sleep(orch: Orchestrator, text: str, *, when: int = 1):
    """第 `when` 次带时长的等待（即某条气泡的 typing 停顿）时，从 transport 喂进一条用户输入，
    并让出循环足够多次，使摄入协程跑完 usher 分流。"""
    state = {"n": 0}

    async def sleep(s):
        if s > 0:
            state["n"] += 1
            if state["n"] == when:
                orch.transport.feed(InboundMessage(speaker="用户", text=text))
                for _ in range(3):
                    await asyncio.sleep(0)
        await asyncio.sleep(0)

    return sleep


def test_key_interrupt_drops_pending_bubbles_and_world_responds_next_beat():
    store = Store(":memory:")
    orch = _orch(store=store)
    orch._sleep = _interrupting_sleep(orch, "等等，我打断一下")
    with _Events() as ev:
        turns = asyncio.run(orch.run(max_turns=2))

    assert turns == 2
    tr = orch.transport
    # 第一拍：小丸子只说出第一句；第二、三句在等节奏时被抢占，不发
    # 第二拍：user_forced → reseed → 阿福回应用户
    assert [t for _, t in tr.sent] == ["第一句", "你说什么？"]
    assert tr.system_sent == ["小丸子的话说到一半，停住了。"]
    # 历史：只有说出口的进史；被丢弃的没发生过；用户输入落在第一句之后
    texts = [(m.speaker, m.text) for m in orch.room.history]
    assert texts == [("小丸子", "第一句"), ("用户", "等等，我打断一下"), ("阿福", "你说什么？")]
    assert store.count_messages(orch.room_id) == 3
    # 事件：interrupt + beat_aborted(perform) 各一次，丢了 2 条
    assert ev.of("interrupt")[0]["dropped"] == 2
    aborted = ev.of("beat_aborted")
    assert len(aborted) == 1 and aborted[0]["stage"] == "perform" and aborted[0]["dropped"] == 2
    assert orch.delivery.idle and orch.delivery.beat == 1


def test_absorbed_input_does_not_preempt():
    # 附和：不抢占，当前 beat 演完（三句都发），用户输入按时间落在中间
    orch = _orch()
    orch._sleep = _interrupting_sleep(orch, "嗯嗯")
    with _Events() as ev:
        asyncio.run(orch.run(max_turns=1))
    assert [t for _, t in orch.transport.sent] == ["第一句", "第二句", "第三句"]
    assert orch.transport.system_sent == []
    assert ev.of("interrupt") == [] and ev.of("beat_aborted") == []
    assert [m.speaker for m in orch.room.history] == ["小丸子", "用户", "小丸子", "小丸子"]


def test_interrupt_during_generation_discards_whole_turn():
    # 抢占落在生成期间（gateway.complete 还没回来）：生成回来后整批作废，一条都不发
    orch = _orch()
    inner = orch.gateway

    class InterruptingGateway:
        def complete(self, system, messages, model_id, max_tokens=1024):
            if self.first:
                self.first = False
                loop.call_soon_threadsafe(orch.interrupt, "test")   # 循环线程里抢占
            return inner.complete(system, messages, model_id, max_tokens)

        first = True

    orch.gateway = InterruptingGateway()
    loop = asyncio.new_event_loop()
    with _Events() as ev:
        turns = loop.run_until_complete(orch.run(max_turns=2))
    loop.close()

    assert turns == 2
    # 第一拍（小丸子三句）整批作废；第二拍阿福正常
    assert [t for _, t in orch.transport.sent] == ["你说什么？"]
    aborted = ev.of("beat_aborted")
    assert any(a["stage"] == "generate" and a["dropped"] == 3 for a in aborted)
    assert [m.speaker for m in orch.room.history] == ["阿福"]
