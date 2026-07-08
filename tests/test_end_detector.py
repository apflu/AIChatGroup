"""EndDetector：会话结束检测的四种 reason + TensionReader 启发式。"""
from aichatgroup.domain import (
    DEADLOCK,
    INTENT_FULFILLED,
    LULL,
    MAX_LENGTH,
    ConversationIntent,
    RoomState,
)
from aichatgroup.message.conductor import (
    EndDetector,
    FlatTensionReader,
    StagnationTensionReader,
)


def _room_with(speakers):
    room = RoomState()
    for s in speakers:
        room.append(s, "……")
    return room


def test_lull_after_consecutive_silence():
    d = EndDetector(lull_patience=2)
    d.begin(ConversationIntent())
    room = RoomState()
    d.observe(room, spoke=False)
    assert d.check(room) is None          # 只 1 拍留白，还没到耐心上限
    d.observe(room, spoke=False)
    end = d.check(room)
    assert end is not None and end.reason == LULL


def test_speech_resets_silence_run():
    d = EndDetector(lull_patience=2)
    d.begin(ConversationIntent())
    room = RoomState()
    d.observe(room, spoke=False)
    d.observe(room, spoke=True)           # 有人说话 → 清零留白计数
    d.observe(room, spoke=False)
    assert d.check(room) is None          # 不该判 lull


def test_intent_fulfilled_on_length_budget():
    d = EndDetector()
    d.begin(ConversationIntent(length_budget=3))
    room = RoomState()
    for _ in range(2):
        d.observe(room, spoke=True)
        assert d.check(room) is None
    d.observe(room, spoke=True)           # 第 3 次发言 = 跑满预算
    end = d.check(room)
    assert end is not None and end.reason == INTENT_FULFILLED


def test_max_length_backstop():
    d = EndDetector(max_beats=3, lull_patience=99)
    d.begin(ConversationIntent())
    room = RoomState()
    for _ in range(2):
        d.observe(room, spoke=True)
        assert d.check(room) is None
    d.observe(room, spoke=True)
    end = d.check(room)
    assert end is not None and end.reason == MAX_LENGTH


def test_flat_reader_disables_deadlock():
    # 默认 FlatTensionReader → 恒 0 张力 → 永不 deadlock，哪怕两人反复对峙
    d = EndDetector(deadlock_window=2, deadlock_tension=0.7, max_beats=99, lull_patience=99)
    d.begin(ConversationIntent())
    room = _room_with(["甲", "乙"] * 5)
    for _ in range(6):
        d.observe(room, spoke=True)
    assert d.check(room) is None


def test_deadlock_with_stagnation_reader():
    # 少数角色头对头 → StagnationTensionReader 读高张力 → 僵持够久 → deadlock
    reader = StagnationTensionReader(window=4, hot=0.9)
    d = EndDetector(
        deadlock_window=3, deadlock_tension=0.7, max_beats=99, lull_patience=99,
        tension_reader=reader,
    )
    d.begin(ConversationIntent())
    room = _room_with(["甲", "乙"] * 4)   # 8 条，最近 4 条只有 2 个说话者
    end = None
    for _ in range(4):
        d.observe(room, spoke=True)
        end = d.check(room)
        if end:
            break
    assert end is not None and end.reason == DEADLOCK
    assert end.tension >= 0.7


def test_stagnation_reader_cold_when_many_speakers():
    reader = StagnationTensionReader(window=4)
    room = _room_with(["甲", "乙", "丙", "丁"])   # 4 个不同说话者
    assert reader.read(room, None) == reader.cold


def test_flat_reader_is_default():
    d = EndDetector()
    assert isinstance(d.tension_reader, FlatTensionReader)
