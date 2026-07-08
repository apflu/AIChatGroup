"""基础 compaction：超阈值时摘要化最老段、沉入第 1 层、裁剪历史。"""
from aichatgroup.domain import RoomState, WorldBook
from aichatgroup.domain.types import GatewayResponse, Usage
from aichatgroup.story.memory import maybe_compact


class FakeGateway:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list = []

    def complete(self, system, messages, model_id, max_tokens=1024):
        self.calls.append((system, messages, model_id))
        return GatewayResponse(text=self.text, usage=Usage())


def _world():
    return WorldBook(bible="热闹的酒馆。", rules="遵守设定。")


def test_no_compaction_below_threshold():
    room = RoomState()
    for i in range(3):
        room.append("小丸子", f"第{i}句")
    gw = FakeGateway("SUMMARY")
    result = maybe_compact(gw, _world(), room, "haiku", max_history=5, keep_last=2)
    assert result.compacted is False
    assert len(room.history) == 3
    assert gw.calls == []  # 未触发 → 不调用模型


def test_compaction_summarizes_and_trims():
    room = RoomState(long_term_summary="旧摘要")
    for i in range(6):
        room.append("小丸子", f"第{i}句")
    gw = FakeGateway("合并后的新摘要")
    result = maybe_compact(gw, _world(), room, "haiku", max_history=4, keep_last=2)

    assert result.compacted is True
    assert result.dropped == 4                      # 6 - keep_last(2)
    assert room.long_term_summary == "合并后的新摘要"
    # 只保留最后 2 条
    assert [m.text for m in room.history] == ["第4句", "第5句"]
    # 旧摘要被作为上下文喂给了模型
    assert "旧摘要" in gw.calls[0][1][0]["content"]
