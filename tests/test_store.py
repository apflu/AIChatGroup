"""SQLite Store：去重、记忆/摘要 upsert、trim、load_room_state。"""
from aichatgroup.persistence import Store


def _store():
    return Store(":memory:")


def test_message_dedup_by_external_id():
    s = _store()
    rid = s.ensure_room("r1")
    assert s.append_message(rid, "小丸子", "你好", external_id="c:1") is True
    # 同一 external_id 再来一次 → 不插入
    assert s.append_message(rid, "小丸子", "你好", external_id="c:1") is False
    assert s.count_messages(rid) == 1
    # 无 external_id 的引擎自产气泡不受去重约束，可重复插入
    assert s.append_message(rid, "阿福", "在") is True
    assert s.append_message(rid, "阿福", "在") is True
    assert s.count_messages(rid) == 3


def test_ensure_room_is_idempotent():
    s = _store()
    a = s.ensure_room("r1")
    b = s.ensure_room("r1")
    c = s.ensure_room("r2")
    assert a == b
    assert a != c


def test_memory_upsert_and_load():
    s = _store()
    rid = s.ensure_room("r1")
    s.save_memory(rid, "a1", '{"mood": "兴奋"}')
    s.save_memory(rid, "a1", '{"mood": "平静"}')  # 覆盖
    s.save_memory(rid, "a2", '{"note": "x"}')
    mem = s.load_memory(rid)
    assert mem["a1"] == '{"mood": "平静"}'
    assert mem["a2"] == '{"note": "x"}'


def test_summary_upsert_and_load():
    s = _store()
    rid = s.ensure_room("r1")
    assert s.load_summary(rid) == ("", "")
    s.save_summary(rid, "摘要A", "关系A")
    s.save_summary(rid, "摘要B", "关系B")
    assert s.load_summary(rid) == ("摘要B", "关系B")


def test_trim_history_keeps_last_n():
    s = _store()
    rid = s.ensure_room("r1")
    for i in range(10):
        s.append_message(rid, "小丸子", f"第{i}句")
    dropped = s.trim_history(rid, keep_last=3)
    assert dropped == 7
    remaining = s.load_history(rid)
    assert [m.text for m in remaining] == ["第7句", "第8句", "第9句"]


def test_load_room_state_composes():
    s = _store()
    rid = s.ensure_room("r1")
    s.save_summary(rid, "长期摘要", "客观关系")
    s.append_message(rid, "小丸子", "嗨")
    s.save_memory(rid, "a1", '{"k": 1}')
    room = s.load_room_state(rid)
    assert room.long_term_summary == "长期摘要"
    assert room.objective_relations == "客观关系"
    assert [m.speaker for m in room.history] == ["小丸子"]
    assert room.memory["a1"] == '{"k": 1}'
