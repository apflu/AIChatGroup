"""Director：RoundRobin 公平轮流 + ModelDirector 选择/兜底/留白。"""
from aichatgroup.domain import Agent, RoomState
from aichatgroup.domain.types import GatewayResponse, Usage
from aichatgroup.message.conductor import ModelDirector, RoundRobinDirector, consecutive_count


def _agents():
    return [
        Agent(id="a1", name="小丸子", model_id="m"),
        Agent(id="a2", name="阿福", model_id="m"),
        Agent(id="a3", name="小诗", model_id="m"),
    ]


class FakeGateway:
    """按固定文本应答，记录调用。"""

    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list = []

    def complete(self, system, messages, model_id, max_tokens=1024):
        self.calls.append((system, messages, model_id, max_tokens))
        return GatewayResponse(text=self.text, usage=Usage())


def test_round_robin_is_fair_and_skips_last_speaker():
    agents = _agents()
    d = RoundRobinDirector()
    room = RoomState()
    picked = []
    for _ in range(4):
        sid = d.next_speaker(room, agents)
        picked.append(sid)
        # 模拟该角色说了一句，进历史
        name = next(a.name for a in agents if a.id == sid)
        room.append(name, "……")
    # 公平轮流，且从不连着选同一个
    assert picked == ["a1", "a2", "a3", "a1"]


def test_consecutive_count_helper():
    room = RoomState()
    room.append("小丸子", "1")
    room.append("小丸子", "2")
    room.append("阿福", "3")
    assert consecutive_count(room, "阿福") == 1
    room.append("阿福", "4")
    assert consecutive_count(room, "阿福") == 2


def test_model_director_picks_returned_id():
    agents = _agents()
    d = ModelDirector(FakeGateway("a2"), model_id="haiku")
    assert d.next_speaker(RoomState(), agents) == "a2"


def test_model_director_none_means_silence():
    agents = _agents()
    d = ModelDirector(FakeGateway("none"), model_id="haiku", allow_silence=True)
    assert d.next_speaker(RoomState(), agents) is None


def test_model_director_excludes_over_talker_and_falls_back():
    agents = _agents()
    # 小丸子已连说 2 次，达到 max_consecutive → 本拍被排除
    room = RoomState()
    room.append("小丸子", "1")
    room.append("小丸子", "2")
    # 模型偏要选被排除的 a1（非法）→ 兜底到首个合法候选（a2）
    d = ModelDirector(FakeGateway("a1"), model_id="haiku", max_consecutive=2)
    sid = d.next_speaker(room, agents)
    assert sid != "a1"
    assert sid in ("a2", "a3")


def test_model_director_tolerates_noisy_output():
    agents = _agents()
    d = ModelDirector(FakeGateway("我觉得应该让 a3 来说"), model_id="haiku")
    assert d.next_speaker(RoomState(), agents) == "a3"


def test_model_director_falls_back_on_gateway_error():
    class BoomGateway:
        def complete(self, *a, **k):
            raise RuntimeError("network down")

    d = ModelDirector(BoomGateway(), model_id="haiku")
    sid = d.next_speaker(RoomState(), _agents())
    assert sid == "a1"  # 异常 → 规则兜底首个候选
