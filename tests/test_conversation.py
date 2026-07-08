"""会话状态机：seed→run→end→reseed、usher user_forced 提前收束、会话持久化。"""
import asyncio

from aichatgroup.domain import LULL, USER_FORCED, Agent, ConversationEnd, WorldBook
from aichatgroup.io.gateway import MockGateway
from aichatgroup.io.persistence import Store
from aichatgroup.io.transport import InboundMessage, InMemoryTransport
from aichatgroup.message.conductor import EndDetector, RoundRobinConductor
from aichatgroup.message.usher import Usher, UsherDecision
from aichatgroup.runtime import Orchestrator
from aichatgroup.story.storyteller import StubStoryteller


async def _fast_sleep(_seconds: float) -> None:
    await asyncio.sleep(0)


def _world():
    return WorldBook(bible="热闹的酒馆世界。" * 3, rules="遵守世界书。" * 3)


def _agents():
    return [
        Agent(id="a1", name="小丸子", model_id="m1", base_prompt="活泼。"),
        Agent(id="a2", name="阿福", model_id="m2", base_prompt="沉稳。"),
        Agent(id="a3", name="小诗", model_id="m3", base_prompt="爱押韵。"),
    ]


def _gateway():
    gw = MockGateway()
    gw.push_script("小丸子", ["哟！", "又来啦"])
    gw.push_script("阿福", ["慢品。"])
    gw.push_script("小诗", ["灯火明。"])
    return gw


class ScriptedConductor:
    """按固定序列返回 speaker_id 或 None（None = 留白），序列耗尽后恒 None。"""

    def __init__(self, seq):
        self.seq = list(seq)
        self.i = 0

    def next_speaker(self, room, agents):
        if self.i < len(self.seq):
            v = self.seq[self.i]
            self.i += 1
            return v
        return None


class SpyStoryteller:
    """记录每次 seed 收到的 last_end，用于断言 reseed 交接。"""

    def __init__(self):
        self.last_ends = []
        self._inner = StubStoryteller()

    def seed(self, room, last_end):
        self.last_ends.append(last_end)
        return self._inner.seed(room, last_end)


class FakeUsherGateway:
    def __init__(self, verdict: str):
        self.verdict = verdict

    def complete(self, system, messages, model_id, max_tokens=1024):
        from aichatgroup.domain.types import GatewayResponse, Usage
        return GatewayResponse(text=self.verdict, usage=Usage())


def _make_orch(*, conductor, store=None, storyteller=None, usher=None, detector=None):
    return Orchestrator(
        world=_world(), agents=_agents(), gateway=_gateway(),
        conductor=conductor, transport=InMemoryTransport(),
        storyteller=storyteller, usher=usher, end_detector=detector,
        store=store, max_tokens=64, turn_interval_s=0.0, idle_poll_s=0.0,
        sleep=_fast_sleep,
    )


def test_normal_run_is_one_open_conversation():
    # RoundRobin(never None) + Flat(no deadlock) + 无预算 → 一整段会话，不被切碎
    store = Store(":memory:")
    orch = _make_orch(conductor=RoundRobinConductor(), store=store)
    asyncio.run(orch.run(max_turns=4))
    assert store.count_conversations(orch.room_id) == 1
    convs = store.recent_conversations(orch.room_id)
    assert convs[0]["end_reason"] is None      # 仍开着（run 结束时未收束）
    # 所有气泡都挂到了这段会话
    rows = store.conn.execute(
        "SELECT conversation_id FROM messages WHERE room_id=?", (orch.room_id,)
    ).fetchall()
    assert all(r["conversation_id"] == convs[0]["id"] for r in rows)


def test_lull_ends_conversation_and_reseeds():
    # 说一句 → 连续两拍留白 → lull → 收束 + reseed；如此三段
    seq = ["a1", None, None, "a2", None, None, "a3"]
    spy = SpyStoryteller()
    store = Store(":memory:")
    orch = _make_orch(
        conductor=ScriptedConductor(seq), store=store, storyteller=spy,
        detector=EndDetector(lull_patience=2, max_beats=99),
    )
    asyncio.run(orch.run(max_turns=3))
    # 至少两段以 lull 收束
    lull_ends = [e for e in spy.last_ends if e is not None and e.reason == LULL]
    assert len(lull_ends) >= 2
    reasons = [
        r["end_reason"] for r in store.recent_conversations(orch.room_id, limit=10)
    ]
    assert reasons.count(LULL) >= 2


def test_usher_escalate_sets_forced_end():
    usher = Usher(FakeUsherGateway("disrupt"), model_id="haiku")
    orch = _make_orch(conductor=RoundRobinConductor(), usher=usher)
    orch._handle_inbound(InboundMessage(speaker="用户", text="我掀了桌子！"))
    assert orch._forced_end is not None
    assert orch._forced_end.reason == USER_FORCED
    assert orch._forced_end.direction == "disrupt"
    assert "掀" in orch._forced_end.summary_hook


def test_usher_absorb_does_not_force_end():
    usher = Usher(FakeUsherGateway("absorb"), model_id="haiku")
    orch = _make_orch(conductor=RoundRobinConductor(), usher=usher)
    orch._handle_inbound(InboundMessage(speaker="用户", text="哈哈对啊"))
    assert orch._forced_end is None


def test_forced_end_consumed_by_loop_and_reseeds():
    spy = SpyStoryteller()
    orch = _make_orch(conductor=RoundRobinConductor(), storyteller=spy)
    orch._forced_end = ConversationEnd(reason=USER_FORCED, summary_hook="炸弹", direction="disrupt")
    asyncio.run(orch.run(max_turns=1))
    # 第一段 seed(last_end=None)，随后消费 forced_end → reseed(last_end=user_forced)
    assert orch._forced_end is None
    forced_seeds = [e for e in spy.last_ends if e is not None and e.reason == USER_FORCED]
    assert forced_seeds and forced_seeds[0].direction == "disrupt"
