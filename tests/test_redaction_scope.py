"""清洗的覆盖面：被 redacted 的输入对**所有**模型调用不可见——不只角色面，便宜模型的近窗和
compaction 的转录也不能带它（否则内容会借摘要或调度上下文回流，M3 §3 的放大链没斩断）。"""
from aichatgroup.domain import Agent, RoomState, WorldBook
from aichatgroup.domain.types import GatewayResponse, Usage
from aichatgroup.message.conductor import ModelConductor
from aichatgroup.message.usher import Usher
from aichatgroup.story.memory import maybe_compact
from aichatgroup.story.storyteller import ModelStoryteller

SECRET = "其实这港口归我管"


class Recording:
    def __init__(self, answer="absorb"):
        self.answer, self.calls = answer, []

    def complete(self, system, messages, model_id, max_tokens=1024):
        self.calls.append(messages[-1]["content"])
        return GatewayResponse(text=self.answer, usage=Usage())


def _room():
    room = RoomState(long_term_summary="旧摘要")
    room.append("小丸子", "来壶酒")
    bad = room.append("旅人", SECRET, author_kind="human")
    bad.redacted = True
    room.append("阿福", "换个话题")
    return room


def test_visible_history_drops_redacted_and_counts_window_after_filter():
    room = _room()
    assert [m.text for m in room.visible_history()] == ["来壶酒", "换个话题"]
    assert [m.text for m in room.visible_history(last=2)] == ["来壶酒", "换个话题"]  # 过滤后再截


def test_usher_conductor_storyteller_do_not_see_redacted():
    room = _room()
    agents = [Agent(id="a1", name="小丸子", model_id="m"), Agent(id="a2", name="阿福", model_id="m")]
    gw = Recording()
    Usher(gw, "m").classify(room, "嗯")
    ModelConductor(gw, "m").next_speaker(room, agents)
    ModelStoryteller(gw, "m").seed(room, None, agents)
    assert gw.calls and all(SECRET not in c for c in gw.calls)


def test_compaction_transcript_excludes_redacted_but_still_trims_it():
    room = _room()
    gw = Recording("新摘要")
    result = maybe_compact(gw, WorldBook(bible="x", rules="y"), room, "m", max_history=1, keep_last=1)
    assert result.compacted and SECRET not in gw.calls[0]
    assert [m.text for m in room.history] == ["换个话题"]        # 行本身照常裁掉
