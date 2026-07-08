"""回复寻址端到端：入站解析、出站定向+持久化、builder 句柄与超窗内联重注入。"""
import asyncio

from aichatgroup.message.conductor import RoundRobinDirector
from aichatgroup.domain import Agent, RoomState, WorldBook
from aichatgroup.io.gateway import MockGateway
from aichatgroup.io.persistence import Store
from aichatgroup.message.prompt import build_prompt
from aichatgroup.runtime import Orchestrator
from aichatgroup.io.transport import InboundMessage, InMemoryTransport


async def _fast(_s):
    await asyncio.sleep(0)


def _world():
    return WorldBook(bible="热闹的酒馆。" * 3, rules="遵守世界书。" * 3)


def _maru():
    return Agent(id="a1", name="小丸子", model_id="claude-opus-4-8", base_prompt="活泼。")


def _orch(store, gw):
    return Orchestrator(
        world=_world(), agents=[_maru()], gateway=gw,
        director=RoundRobinDirector(), transport=InMemoryTransport(),
        store=store, turn_interval_s=0.0, idle_poll_s=0.0, sleep=_fast,
    )


def test_inbound_reply_resolves_to_internal_id():
    store = Store(":memory:")
    gw = MockGateway()
    gw.push_script("小丸子", ["嗨"])
    orch = _orch(store, gw)
    asyncio.run(orch.run(max_turns=1))          # 小丸子发"嗨" → ext "mem:0"，store id 1

    bot_msg = orch.room.history[0]
    orch._handle_inbound(InboundMessage(
        speaker="PL", text="回你一句", external_id="c:5",
        reply_to_external_id=bot_msg.meta["external_id"],
    ))
    last = orch.room.history[-1]
    assert last.speaker == "PL"
    assert last.reply_to == bot_msg.id                       # 入站回复解析到内部 id
    assert store.load_history(orch.room_id)[-1].reply_to == bot_msg.id  # 落列


def test_outbound_reply_targets_and_persists():
    store = Store(":memory:")
    gw = MockGateway()
    gw.push_script("小丸子", ["嗨", "{{REPLY:1}}收到"])       # 回合2 回复 ⟦1⟧
    orch = _orch(store, gw)
    asyncio.run(orch.run(max_turns=2))

    rec = orch.transport.sent_records[-1]
    assert rec["text"] == "收到"
    assert rec["reply_to"] == "mem:0"                        # 发送时带上被回复消息的 external_id
    assert store.load_history(orch.room_id)[-1].reply_to == 1  # 持久化 reply_to_id


def test_builder_renders_handle_and_reply_note():
    room = RoomState()
    room.append("小丸子", "我请客！")                          # id 1
    room.append("阿福", "那我不客气了", reply_to=1)             # id 2 → 回 1
    agent = Agent(id="a2", name="阿福", model_id="m")
    _, messages = build_prompt(_world(), room, agent)

    first = messages[0]["content"]                            # 非末条历史 → 纯文本
    assert "⟦1⟧ [小丸子]" in first
    last_hist = messages[-2]["content"][0]["text"]            # 末条历史 → 带缓存块
    assert "⟦2⟧ [阿福]" in last_hist
    assert "（回⟦1⟧「我请客！" in last_hist                     # 近窗内引用


def test_cross_window_reply_reinjects_from_store():
    store = Store(":memory:")
    rid = store.ensure_room("r")
    old = store.append_message(rid, "小丸子", "很久以前我说过的话", external_id="c:1")
    # room 里只有一条新消息，回复那条已滑出窗口的旧消息
    room = RoomState()
    new_id = store.append_message(rid, "阿福", "接着那句说")
    room.append("阿福", "接着那句说", id=new_id, reply_to=old)
    agent = Agent(id="a2", name="阿福", model_id="m")

    _, messages = build_prompt(
        _world(), room, agent, resolve=lambda mid: store.get_message(rid, mid)
    )
    txt = messages[0]["content"][0]["text"]                   # 唯一历史条（末条→带缓存块）
    assert f"（回⟦{old}⟧「很久以前" in txt                       # 超窗目标从 store 取回内联
