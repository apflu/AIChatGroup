"""Usher：用户输入台口分流 —— 解析/路由契约 + 保守兜底。

注：模型的**语义判断**（如"安静的 canon 破坏也该 escalate"）由 system prompt 承担，
不是单元测试能用 FakeGateway 断言的；这里只锁「给定模型输出 → 决策」的契约与兜底。
"""
import pytest

from aichatgroup.domain import RoomState
from aichatgroup.domain.types import GatewayResponse, Usage
from aichatgroup.message.usher import DIRECTIONS, Usher, UsherDecision


class FakeGateway:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list = []

    def complete(self, system, messages, model_id, max_tokens=1024):
        self.calls.append((system, messages, model_id, max_tokens))
        return GatewayResponse(text=self.text, usage=Usage())


def _usher(text: str) -> Usher:
    return Usher(FakeGateway(text), model_id="haiku")


def test_absorb_means_no_escalation():
    d = _usher("absorb").classify(RoomState(), "今天天气不错")
    assert d.escalate is False
    assert d.absorb is True
    assert d.direction == ""


@pytest.mark.parametrize("word", DIRECTIONS)
def test_each_direction_escalates_with_label(word):
    d = _usher(word).classify(RoomState(), "我掏出手机")
    assert d.escalate is True
    assert d.direction == word


def test_tolerates_noisy_output():
    d = _usher("我觉得这句得 disrupt 一下").classify(RoomState(), "……")
    assert d.escalate is True
    assert d.direction == "disrupt"


def test_direction_without_violate_is_not_violation():
    # 合法强推：有方向、无 violate → escalate 但不清洗
    d = _usher("advance").classify(RoomState(), "我提议大家去码头")
    assert d.escalate is True and d.direction == "advance"
    assert d.violation is False


def test_direction_plus_violate_flags_violation():
    # 抵触 canon：方向 + violate → escalate 且待清洗（violate 在方向词后仍被扫到）
    d = _usher("disrupt violate").classify(RoomState(), "我是隐藏领主")
    assert d.escalate is True and d.direction == "disrupt"
    assert d.violation is True


def test_violate_only_defaults_to_disrupt_escalation():
    # 只说 violate 没给方向：canon 破坏本质捣乱 → 兜底 disrupt + violation
    d = _usher("violate").classify(RoomState(), "世界规则由我改写")
    assert d.escalate is True and d.direction == "disrupt"
    assert d.violation is True


def test_absorb_is_never_a_violation():
    d = _usher("absorb").classify(RoomState(), "今天天气不错")
    assert d.escalate is False and d.violation is False


def test_unparseable_defaults_to_absorb():
    # 拿不准 → 保守放行（误判只赔延迟，不赔丢失）
    d = _usher("嗯？说不好").classify(RoomState(), "……")
    assert d.escalate is False


def test_gateway_error_defaults_to_absorb():
    class BoomGateway:
        def complete(self, *a, **k):
            raise RuntimeError("network down")

    d = Usher(BoomGateway(), model_id="haiku").classify(RoomState(), "……")
    assert d.escalate is False
    assert isinstance(d, UsherDecision)


def test_recent_history_is_fed_as_context():
    room = RoomState()
    room.append("小丸子", "老陈上酒！")
    g = FakeGateway("absorb")
    Usher(g, model_id="haiku").classify(room, "我也要一杯")
    # 最近对话被拼进 user 消息，供模型判断"要不要世界回应"
    sent = g.calls[0][1][0]["content"]
    assert "老陈上酒" in sent
    assert "我也要一杯" in sent
