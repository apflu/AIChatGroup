"""Orchestrator：全循环发言/发送/持久化、摄入去重、开关命令。"""
import asyncio

from aichatgroup.message.conductor import RoundRobinDirector
from aichatgroup.domain import Agent, RoomState, WorldBook
from aichatgroup.io.gateway import MockGateway
from aichatgroup.io.persistence import Store
from aichatgroup.runtime import Orchestrator
from aichatgroup.io.transport import InboundMessage, InMemoryTransport


async def _fast_sleep(_seconds: float) -> None:
    await asyncio.sleep(0)  # 不真的等待，但让出事件循环，保证协程协作调度


def _world():
    return WorldBook(bible="热闹的酒馆世界。" * 3, rules="遵守世界书。" * 3)


def _agents():
    return [
        Agent(id="a1", name="小丸子", model_id="claude-opus-4-8", base_prompt="活泼吵闹。"),
        Agent(id="a2", name="阿福", model_id="claude-sonnet-5", base_prompt="沉稳。"),
        Agent(id="a3", name="小诗", model_id="claude-haiku-4-5", base_prompt="爱押韵。"),
    ]


def _mock_gateway() -> MockGateway:
    gw = MockGateway()
    gw.push_script("小丸子", [
        '哟！{{SEPARATOR}}老陈来壶酒\n{{MEMORY}}{"mood": "兴奋"}',  # 2 气泡 + 记忆
        '哈哈哈',                                                     # 1 气泡（第 4 回合）
    ])
    gw.push_script("阿福", ['急什么，酒要慢品。'])
    gw.push_script("小诗", ['港口灯火明，杯中岁月长。'])
    return gw


def _make_orch(store=None):
    return Orchestrator(
        world=_world(),
        agents=_agents(),
        gateway=_mock_gateway(),
        director=RoundRobinDirector(),
        transport=InMemoryTransport(),
        store=store,
        max_tokens=256,
        turn_interval_s=0.0,
        idle_poll_s=0.0,
        sleep=_fast_sleep,
    )


def test_full_loop_speaks_persists_and_orders():
    store = Store(":memory:")
    orch = _make_orch(store=store)
    turns = asyncio.run(orch.run(max_turns=4))

    assert turns == 4
    transport = orch.transport
    # round-robin 公平顺序：a1, a2, a3, a1
    sent_agents = [aid for aid, _ in transport.sent]
    assert sent_agents == ["a1", "a1", "a2", "a3", "a1"]  # a1 首回合 2 气泡
    # 气泡文本顺序
    assert [t for _, t in transport.sent] == [
        "哟！", "老陈来壶酒", "急什么，酒要慢品。", "港口灯火明，杯中岁月长。", "哈哈哈",
    ]
    # typing 每条气泡前都发过
    assert len(transport.typing_calls) == 5

    # 持久化：共享历史 5 条，记忆增量落库
    assert store.count_messages(orch.room_id) == 5
    assert "兴奋" in store.load_memory(orch.room_id)["a1"]


def test_full_loop_without_store():
    orch = _make_orch(store=None)
    turns = asyncio.run(orch.run(max_turns=2))
    assert turns == 2
    assert len(orch.room.history) == 3  # a1(2) + a2(1)


def test_ingest_dedup_via_external_id():
    store = Store(":memory:")
    orch = _make_orch(store=store)
    msg = InboundMessage(speaker="路人", text="大家好", external_id="c:100")
    orch._handle_inbound(msg)
    orch._handle_inbound(msg)  # 同 external_id → 去重
    assert store.count_messages(orch.room_id) == 1
    assert len(orch.room.history) == 1


def test_command_toggles_switch():
    orch = _make_orch(store=None)
    assert orch.switch.paused is False
    orch._handle_inbound(InboundMessage(speaker="PL", text="/pause"))
    assert orch.switch.paused is True
    orch._handle_inbound(InboundMessage(speaker="PL", text="/resume"))
    assert orch.switch.paused is False
    # 命令不进聊天历史
    assert orch.room.history == []


class _FlakyGateway:
    """包一层 MockGateway，指定 model_id 时抛错，模拟某 provider 抽风。"""

    def __init__(self, inner, fail_model):
        self.inner = inner
        self.fail_model = fail_model

    def complete(self, system, messages, model_id, max_tokens=1024):
        if model_id == self.fail_model:
            raise RuntimeError("boom 401")
        return self.inner.complete(system, messages, model_id, max_tokens)


def test_one_provider_failure_does_not_crash_loop():
    inner = MockGateway()
    inner.push_script("小丸子", ["嗨"])
    inner.push_script("小诗", ["灯火明"])
    gw = _FlakyGateway(inner, fail_model="claude-sonnet-5")  # 阿福那家抽风
    orch = Orchestrator(
        world=_world(), agents=_agents(), gateway=gw,
        director=RoundRobinDirector(), transport=InMemoryTransport(),
        turn_interval_s=0.0, idle_poll_s=0.0, sleep=_fast_sleep,
    )
    turns = asyncio.run(orch.run(max_turns=3))  # round-robin: a1, a2(失败), a3

    assert turns == 3                            # 失败回合仍计数，有界运行能收尾
    sent = [aid for aid, _ in orch.transport.sent]
    assert sent == ["a1", "a3"]                  # 阿福(a2)没发，但没拖垮循环
    assert [t for _, t in orch.transport.sent] == ["嗨", "灯火明"]


def test_startup_loads_only_near_window_not_full_history():
    # 持久 sqlite 跨运行累积全部消息；启动只该把近窗灌进 room.history，
    # 否则模型会看到旧 ⟦id⟧ 并回复失效的 telegram message_id（"Message to be replied not found"）。
    store = Store(":memory:")
    rid = store.ensure_room("default")
    for i in range(30):
        store.append_message(rid, "小丸子", f"旧消息{i}", external_id=f"c:{i}")
    orch = Orchestrator(
        world=_world(), agents=_agents(), gateway=_mock_gateway(),
        director=RoundRobinDirector(), transport=InMemoryTransport(),
        store=store, max_history=10, keep_last=5,
        turn_interval_s=0.0, idle_poll_s=0.0, sleep=_fast_sleep,
    )
    assert len(orch.room.history) == 10                 # 只近窗（max_history），非全部 30 条
    assert orch.room.history[-1].text == "旧消息29"     # 保留的是最近的
    assert orch.room.history[0].text == "旧消息20"


def test_outbound_reply_to_out_of_window_id_sends_without_reply():
    # 回复一个已滑出近窗的旧 id：不该把陈旧 external_id 传给 telegram（会 not found），
    # target_ext 应为 None（超窗引用靠 builder 内联，不挂 telegram reply）。
    store = Store(":memory:")
    rid = store.ensure_room("default")
    old = store.append_message(rid, "小丸子", "很旧的话", external_id="c:1")
    gw = MockGateway()
    gw.push_script("小丸子", [f"{{{{REPLY:{old}}}}}接着那句"])   # 回复超窗旧 id
    orch = Orchestrator(
        world=_world(), agents=[Agent(id="a1", name="小丸子", model_id="m", base_prompt="活泼。")],
        gateway=gw, director=RoundRobinDirector(), transport=InMemoryTransport(),
        store=store, room=RoomState(),                  # 空 room → old 不在近窗
        turn_interval_s=0.0, idle_poll_s=0.0, sleep=_fast_sleep,
    )
    asyncio.run(orch.run(max_turns=1))
    rec = orch.transport.sent_records[-1]
    assert rec["text"] == "接着那句"
    assert rec["reply_to"] is None                       # 超窗 → 不带 telegram reply
    assert store.load_history(orch.room_id)[-1].reply_to == old  # 但 reply_to_id 仍持久化


def test_agent_cannot_native_reply_another_agents_message():
    # telegram 限制：bot 不能 reply 另一个 bot 的消息 → 不挂 telegram reply（但 reply_to_id 仍存、靠内联表达）
    store = Store(":memory:")
    gw = MockGateway()
    gw.push_script("小丸子", ["先说一句"])                 # id 1（agent 小丸子）
    gw.push_script("阿福", ["{{REPLY:1}}我接你话"])         # 阿福 reply 小丸子（另一个 agent bot）
    orch = Orchestrator(
        world=_world(),
        agents=[
            Agent(id="a1", name="小丸子", model_id="m", base_prompt="活泼。"),
            Agent(id="a2", name="阿福", model_id="m", base_prompt="沉稳。"),
        ],
        gateway=gw, director=RoundRobinDirector(), transport=InMemoryTransport(),
        store=store, turn_interval_s=0.0, idle_poll_s=0.0, sleep=_fast_sleep,
    )
    asyncio.run(orch.run(max_turns=2))
    rec = orch.transport.sent_records[-1]
    assert rec["text"] == "我接你话"
    assert rec["reply_to"] is None                          # 跨 bot → 不挂 telegram reply
    assert store.load_history(orch.room_id)[-1].reply_to == 1  # 但 reply_to_id 仍持久化


def test_agent_can_native_reply_human_message():
    # 角色 bot 能原生 reply 人类消息（telegram 允许 bot reply 用户消息）
    store = Store(":memory:")
    gw = MockGateway()
    gw.push_script("小丸子", ["{{REPLY:1}}回你一句"])
    orch = Orchestrator(
        world=_world(), agents=[Agent(id="a1", name="小丸子", model_id="m", base_prompt="活泼。")],
        gateway=gw, director=RoundRobinDirector(), transport=InMemoryTransport(),
        store=store, turn_interval_s=0.0, idle_poll_s=0.0, sleep=_fast_sleep,
    )
    orch._handle_inbound(InboundMessage(speaker="PL", text="人类发言", external_id="c:9"))  # id 1, human
    asyncio.run(orch.run(max_turns=1))
    rec = orch.transport.sent_records[-1]
    assert rec["text"] == "回你一句"
    assert rec["reply_to"] == "c:9"                          # 人类消息可原生 reply


def test_delivery_splits_gesture_beat_and_speech():
    # 神态(*…*)隐去、举动({{ACT:…}})托管旁白 bot 0、台词由角色 bot 发；历史仍保留完整动作
    gw = MockGateway()
    gw.push_script("小丸子", [
        "*猛地一拍吧台* 哎呀阿福！{{SEPARATOR}}{{ACT:掏出一封信推过去}}给你的",
    ])
    store = Store(":memory:")
    orch = Orchestrator(
        world=_world(), agents=_agents(), gateway=gw,
        director=RoundRobinDirector(), transport=InMemoryTransport(),
        store=store, turn_interval_s=0.0, idle_poll_s=0.0, sleep=_fast_sleep,
    )
    asyncio.run(orch.run(max_turns=1))
    t = orch.transport
    # 角色 bot 只发台词（无动作括号、无神态）
    assert [txt for _, txt in t.sent] == ["哎呀阿福！", "给你的"]
    # 举动交旁白 bot 0 第三人称播报；神态隐去、不播报
    assert t.system_sent == ["小丸子掏出一封信推过去"]
    # 历史/持久化仍保留完整动作（神态+举动括号）→ 模型上下文与缓存不变
    joined = " ".join(m.render() for m in store.load_history(orch.room_id))
    assert "（猛地一拍吧台）" in joined and "（掏出一封信推过去）" in joined


def test_pure_gesture_bubble_sends_nothing_to_chat():
    # 纯神态气泡：聊天流里完全隐去（角色 bot 不发、旁白也不发），但仍入历史
    gw = MockGateway()
    gw.push_script("小丸子", ["*若有所思地摩挲酒杯*{{SEPARATOR}}其实我早想说了"])
    store = Store(":memory:")
    orch = Orchestrator(
        world=_world(), agents=_agents(), gateway=gw,
        director=RoundRobinDirector(), transport=InMemoryTransport(),
        store=store, turn_interval_s=0.0, idle_poll_s=0.0, sleep=_fast_sleep,
    )
    asyncio.run(orch.run(max_turns=1))
    t = orch.transport
    assert [txt for _, txt in t.sent] == ["其实我早想说了"]  # 纯神态那条没发
    assert t.system_sent == []                                # 神态不播报
    assert store.count_messages(orch.room_id) == 2            # 但两条都进历史


def test_paused_blocks_chatter():
    orch = _make_orch(store=None)
    orch.switch.pause()

    # paused 时永远到不了 max_turns（只空转 idle 轮询），转几圈后 request_stop 收尾。
    async def _driver():
        task = asyncio.create_task(orch.run(max_turns=3))
        for _ in range(5):
            await asyncio.sleep(0)  # 让空转循环跑几圈
        orch.request_stop()
        return await task

    turns = asyncio.run(_driver())
    assert turns == 0
    assert orch.transport.sent == []
