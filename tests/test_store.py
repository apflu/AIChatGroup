"""SQLite Store：去重、记忆/摘要 upsert、trim、load_room_state。"""
from aichatgroup.io.persistence import Store


def _store():
    return Store(":memory:")


def test_message_dedup_by_external_id():
    s = _store()
    rid = s.ensure_room("r1")
    first = s.append_message(rid, "小丸子", "你好", external_id="c:1")
    assert first is not None  # 返回新行 id
    # 同一 external_id 再来一次 → 不插入，返回 None
    assert s.append_message(rid, "小丸子", "你好", external_id="c:1") is None
    assert s.count_messages(rid) == 1
    # 无 external_id 的引擎自产气泡不受去重约束，可重复插入
    id2 = s.append_message(rid, "阿福", "在")
    id3 = s.append_message(rid, "阿福", "在")
    assert id2 is not None and id3 is not None and id2 != id3  # id 单调递增
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


def test_reply_to_roundtrip_and_lookups():
    s = _store()
    rid = s.ensure_room("r1")
    a = s.append_message(rid, "小丸子", "我请客！", external_id="c:10")
    b = s.append_message(rid, "阿福", "那我不客气了", reply_to_id=a)
    hist = s.load_history(rid)
    assert hist[1].reply_to == a                       # reply_to_id 落列并下发
    assert hist[0].meta["external_id"] == "c:10"        # external_id 下发到 meta
    assert s.id_for_external(rid, "c:10") == a          # external → 内部 id
    assert s.get_message(rid, a).text == "我请客！"      # 按 id 取回（超窗重注入用）
    assert s.get_message(rid, 999) is None
    assert s.id_for_external(rid, "c:none") is None


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


def test_conversation_lifecycle():
    s = _store()
    rid = s.ensure_room("r1")
    cid = s.start_conversation(rid, kind="chitchat", hook="聊聊天气")
    assert s.count_conversations(rid) == 1
    # 气泡挂到会话
    s.append_message(rid, "小丸子", "今天真热", conversation_id=cid)
    row = s.conn.execute(
        "SELECT conversation_id FROM messages WHERE room_id=?", (rid,)
    ).fetchone()
    assert row["conversation_id"] == cid
    # 未收束时 end_reason 为空
    assert s.get_conversation(cid)["end_reason"] is None
    # 收束
    s.end_conversation(cid, reason="lull", tension=0.3, summary="没人接话")
    conv = s.get_conversation(cid)
    assert conv["end_reason"] == "lull"
    assert conv["tension"] == 0.3
    assert conv["summary"] == "没人接话"


def test_recent_conversations_newest_first():
    s = _store()
    rid = s.ensure_room("r1")
    c1 = s.start_conversation(rid, kind="chitchat")
    c2 = s.start_conversation(rid, kind="develop_plot")
    recent = s.recent_conversations(rid, limit=5)
    assert [c["id"] for c in recent] == [c2, c1]   # 最新在前


def test_conversation_id_column_added_by_migration(tmp_path):
    # 旧库（messages 无 conversation_id 列）→ Store 打开时 _migrate 补列，写入不炸
    import sqlite3
    db = tmp_path / "old.sqlite"
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, room_id INTEGER NOT NULL, "
        "external_id TEXT, speaker TEXT NOT NULL, text TEXT NOT NULL, reply_to_id INTEGER, "
        "ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP);"
    )
    conn.commit()
    conn.close()

    s = Store(db)                                  # 打开旧库 → 触发迁移
    cols = {r["name"] for r in s.conn.execute("PRAGMA table_info(messages)")}
    assert "conversation_id" in cols
    rid = s.ensure_room("r1")
    cid = s.start_conversation(rid, kind="chitchat")
    mid = s.append_message(rid, "小丸子", "hi", conversation_id=cid)
    assert mid is not None
