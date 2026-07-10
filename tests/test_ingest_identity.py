"""摄入身份解析：sender_id→世界名、陌生人兜底、/iam 认领；usher 用世界名。"""
import asyncio

from aichatgroup.domain import Agent, WorldBook
from aichatgroup.domain.player import STRANGER_NAME
from aichatgroup.io.gateway import MockGateway
from aichatgroup.io.persistence import Store
from aichatgroup.io.transport import InboundMessage, InMemoryTransport
from aichatgroup.message.conductor import RoundRobinConductor
from aichatgroup.runtime import Orchestrator
from aichatgroup.runtime.players import PlayerRegistry


def _agents():
    return [Agent(id="a1", name="小丸子", model_id="m")]


def _orch(players=None, store=None):
    return Orchestrator(
        world=WorldBook(bible="酒馆。" * 3, rules="守规矩。" * 3),
        agents=_agents(), gateway=MockGateway(),
        conductor=RoundRobinConductor(), transport=InMemoryTransport(),
        players=players, store=store,
        turn_interval_s=0.0, idle_poll_s=0.0,
    )


def test_registered_sender_uses_world_name():
    reg = PlayerRegistry(agent_names={"小丸子"})
    reg.register("telegram", "555", "银发旅人")
    orch = _orch(players=reg)
    orch._handle_inbound(InboundMessage(
        speaker="apflu 猫猫!", text="对啊", sender_id="555", channel="telegram"))
    assert orch.room.history[-1].speaker == "银发旅人"     # 世界名，不是显示名
    assert orch.room.history[-1].author_kind == "human"


def test_unregistered_sender_is_stranger():
    reg = PlayerRegistry()
    orch = _orch(players=reg)
    orch._handle_inbound(InboundMessage(
        speaker="apflu 猫猫!", text="嗨", sender_id="999", channel="telegram"))
    assert orch.room.history[-1].speaker == STRANGER_NAME


def test_no_registry_falls_back_to_display_name():
    orch = _orch(players=None)
    orch._handle_inbound(InboundMessage(speaker="路人", text="嗨", sender_id="1"))
    assert orch.room.history[-1].speaker == "路人"          # 旧行为不变


def test_iam_registers_and_is_not_appended_to_history():
    reg = PlayerRegistry(agent_names={"小丸子"})
    orch = _orch(players=reg)
    orch._handle_inbound(InboundMessage(
        text="/iam 银发旅人", sender_id="555", channel="telegram", speaker="apflu"))
    # /iam 命令本身不进历史
    assert orch.room.history == []
    # 之后该 sender 说话就用认领的世界名
    orch._handle_inbound(InboundMessage(
        speaker="apflu", text="到了", sender_id="555", channel="telegram"))
    assert orch.room.history[-1].speaker == "银发旅人"


def test_iam_rejects_bad_name_keeps_stranger():
    reg = PlayerRegistry(agent_names={"小丸子"})
    orch = _orch(players=reg)
    orch._handle_inbound(InboundMessage(
        text="/iam 小丸子", sender_id="555", channel="telegram", speaker="apflu"))  # 撞 agent 名
    assert reg.resolve("telegram", "555") is None            # 没注册成功
    orch._handle_inbound(InboundMessage(
        speaker="apflu", text="嗨", sender_id="555", channel="telegram"))
    assert orch.room.history[-1].speaker == STRANGER_NAME     # 仍是陌生人


def test_iam_persists_to_store():
    store = Store(":memory:")
    reg = PlayerRegistry(store, store.ensure_room("default"), agent_names={"小丸子"})
    orch = _orch(players=reg, store=store)
    orch._handle_inbound(InboundMessage(
        text="/iam 银发旅人", sender_id="555", channel="telegram", speaker="apflu"))
    assert any(p["name"] == "银发旅人" for p in store.list_players(orch.room_id))
