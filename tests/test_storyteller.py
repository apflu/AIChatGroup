"""Storyteller：StubStoryteller 惰性 + ModelStoryteller 解析/回落。"""
from aichatgroup.domain import CHITCHAT, DEVELOP_PLOT, USER_FORCED, ConversationEnd, RoomState
from aichatgroup.domain.types import GatewayResponse, Usage
from aichatgroup.story.storyteller import ModelStoryteller, StubStoryteller


class FakeGateway:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list = []

    def complete(self, system, messages, model_id, max_tokens=1024):
        self.calls.append((system, messages, model_id, max_tokens))
        return GatewayResponse(text=self.text, usage=Usage())


class BoomGateway:
    def complete(self, *a, **k):
        raise RuntimeError("network down")


def test_stub_seeds_fixed_chitchat():
    st = StubStoryteller()
    intent = st.seed(RoomState(), last_end=None)
    assert intent.kind == CHITCHAT
    assert intent.hook == ""


def test_model_storyteller_parses_kind_and_hook():
    gw = FakeGateway("KIND: develop_plot\nHOOK: 酒馆突然停电，众人摸黑。")
    st = ModelStoryteller(gw, model_id="opus")
    intent = st.seed(RoomState(), last_end=None)
    assert intent.kind == DEVELOP_PLOT
    assert "停电" in intent.hook


def test_model_storyteller_multiline_hook():
    gw = FakeGateway("KIND: chitchat\nHOOK: 第一行钩子\n继续第二行")
    st = ModelStoryteller(gw, model_id="opus")
    intent = st.seed(RoomState(), last_end=None)
    assert intent.kind == CHITCHAT
    assert "第一行钩子" in intent.hook and "继续第二行" in intent.hook


def test_model_storyteller_unknown_kind_falls_back_to_chitchat():
    gw = FakeGateway("KIND: 乱七八糟\nHOOK: 有个钩子")
    st = ModelStoryteller(gw, model_id="opus")
    intent = st.seed(RoomState(), last_end=None)
    assert intent.kind == CHITCHAT          # 非法 kind → 保守回落
    assert "有个钩子" in intent.hook


def test_model_storyteller_error_falls_back():
    st = ModelStoryteller(BoomGateway(), model_id="opus")
    intent = st.seed(RoomState(), last_end=None)
    assert intent.kind == CHITCHAT
    assert intent.hook == ""


def test_model_storyteller_feeds_last_end_context():
    # user_forced 的 reason/summary/direction 应进 prompt，供定向回应
    gw = FakeGateway("KIND: resolve_tension\nHOOK: 回应用户")
    st = ModelStoryteller(gw, model_id="opus")
    end = ConversationEnd(reason=USER_FORCED, summary_hook="我掀桌子", direction="disrupt")
    st.seed(RoomState(), last_end=end)
    user_prompt = gw.calls[0][1][0]["content"]
    assert USER_FORCED in user_prompt
    assert "我掀桌子" in user_prompt
    assert "disrupt" in user_prompt
