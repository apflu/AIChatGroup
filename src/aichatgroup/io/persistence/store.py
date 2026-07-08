"""SQLite 持久化 —— M1 共享全知的可变会话状态。

存放随对话变化的东西：共享历史（append-only、按 external_id 去重）、每角色私有
记忆快照、长期摘要/客观关系。世界书与角色卡不在这里（它们是手写文件，见 presets）。

去重是关键：Telegram 观察者可能因重启/重投递把同一条消息喂进来两次，
external_id 上的唯一约束保证共享历史里每条外部消息只进一次。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from ...domain.types import ContentPart, Message, RoomState

_SCHEMA = """
CREATE TABLE IF NOT EXISTS rooms (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    room_key  TEXT UNIQUE NOT NULL,
    created_ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id     INTEGER NOT NULL,
    external_id TEXT,
    speaker     TEXT NOT NULL,
    text        TEXT NOT NULL,
    reply_to_id INTEGER,
    ts          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- 仅对「有 external_id」的消息去重；引擎自产的气泡 external_id 为 NULL，不受此约束。
CREATE UNIQUE INDEX IF NOT EXISTS ux_messages_external
    ON messages(room_id, external_id) WHERE external_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS memory_snapshots (
    room_id    INTEGER NOT NULL,
    agent_id   TEXT NOT NULL,
    content    TEXT NOT NULL,
    updated_ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (room_id, agent_id)
);
CREATE TABLE IF NOT EXISTS summaries (
    room_id            INTEGER PRIMARY KEY,
    long_term_summary  TEXT NOT NULL DEFAULT '',
    objective_relations TEXT NOT NULL DEFAULT '',
    updated_ts         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


class Store:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        """轻量迁移：对已存在的旧库补上后加的列（CREATE IF NOT EXISTS 不会补列）。"""
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(messages)")}
        if "reply_to_id" not in cols:
            self.conn.execute("ALTER TABLE messages ADD COLUMN reply_to_id INTEGER")

    def close(self) -> None:
        self.conn.close()

    # ---- rooms ---------------------------------------------------------
    def ensure_room(self, room_key: str) -> int:
        cur = self.conn.execute("SELECT id FROM rooms WHERE room_key = ?", (room_key,))
        row = cur.fetchone()
        if row is not None:
            return int(row["id"])
        cur = self.conn.execute("INSERT INTO rooms(room_key) VALUES (?)", (room_key,))
        self.conn.commit()
        return int(cur.lastrowid)

    # ---- messages ------------------------------------------------------
    def append_message(
        self,
        room_id: int,
        speaker: str,
        text: str,
        external_id: str | None = None,
        reply_to_id: int | None = None,
    ) -> int | None:
        """追加一条共享历史，返回新行的 id（房间内稳定 handle）。

        有 external_id 且重复时返回 None（不插入）——调用方据此判断是否为去重命中。
        reply_to_id 指向被回复消息的内部 id。
        """
        if external_id is not None:
            exists = self.conn.execute(
                "SELECT 1 FROM messages WHERE room_id = ? AND external_id = ?",
                (room_id, external_id),
            ).fetchone()
            if exists is not None:
                return None
        cur = self.conn.execute(
            "INSERT INTO messages(room_id, external_id, speaker, text, reply_to_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (room_id, external_id, speaker, text, reply_to_id),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def _row_to_message(self, r) -> Message:
        meta = {}
        if r["external_id"]:
            meta["external_id"] = r["external_id"]
        return Message(
            id=int(r["id"]),
            speaker=r["speaker"],
            parts=[ContentPart(kind="speech", text=r["text"])],
            reply_to=r["reply_to_id"],
            meta=meta,
        )

    def load_history(self, room_id: int, limit: int | None = None) -> list[Message]:
        sql = ("SELECT id, speaker, text, external_id, reply_to_id "
               "FROM messages WHERE room_id = ? ORDER BY id")
        rows = self.conn.execute(sql, (room_id,)).fetchall()
        msgs = [self._row_to_message(r) for r in rows]
        return msgs[-limit:] if limit is not None else msgs

    def get_message(self, room_id: int, message_id: int) -> Message | None:
        """按内部 id 取一条消息（超窗回复重注入用；可能已被 compaction 删除→None）。"""
        r = self.conn.execute(
            "SELECT id, speaker, text, external_id, reply_to_id "
            "FROM messages WHERE room_id = ? AND id = ?",
            (room_id, message_id),
        ).fetchone()
        return self._row_to_message(r) if r is not None else None

    def id_for_external(self, room_id: int, external_id: str) -> int | None:
        """把 external_id（如 telegram chat:msg）解析成内部 id。"""
        r = self.conn.execute(
            "SELECT id FROM messages WHERE room_id = ? AND external_id = ?",
            (room_id, external_id),
        ).fetchone()
        return int(r["id"]) if r is not None else None

    def count_messages(self, room_id: int) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM messages WHERE room_id = ?", (room_id,)
        ).fetchone()
        return int(row["n"])

    def trim_history(self, room_id: int, keep_last: int) -> int:
        """删除除最后 keep_last 条以外的旧消息，返回删除条数（compaction 用）。"""
        row = self.conn.execute(
            "SELECT id FROM messages WHERE room_id = ? ORDER BY id DESC LIMIT 1 OFFSET ?",
            (room_id, keep_last),
        ).fetchone()
        if row is None:
            return 0
        cutoff = int(row["id"])  # 该 id（含）及更旧的都删
        cur = self.conn.execute(
            "DELETE FROM messages WHERE room_id = ? AND id <= ?", (room_id, cutoff)
        )
        self.conn.commit()
        return cur.rowcount

    # ---- memory --------------------------------------------------------
    def save_memory(self, room_id: int, agent_id: str, content: str) -> None:
        self.conn.execute(
            "INSERT INTO memory_snapshots(room_id, agent_id, content) VALUES (?, ?, ?) "
            "ON CONFLICT(room_id, agent_id) DO UPDATE SET "
            "content = excluded.content, updated_ts = CURRENT_TIMESTAMP",
            (room_id, agent_id, content),
        )
        self.conn.commit()

    def load_memory(self, room_id: int) -> dict[str, str]:
        rows = self.conn.execute(
            "SELECT agent_id, content FROM memory_snapshots WHERE room_id = ?", (room_id,)
        ).fetchall()
        return {r["agent_id"]: r["content"] for r in rows}

    # ---- summaries -----------------------------------------------------
    def save_summary(
        self, room_id: int, long_term_summary: str, objective_relations: str
    ) -> None:
        self.conn.execute(
            "INSERT INTO summaries(room_id, long_term_summary, objective_relations) "
            "VALUES (?, ?, ?) ON CONFLICT(room_id) DO UPDATE SET "
            "long_term_summary = excluded.long_term_summary, "
            "objective_relations = excluded.objective_relations, "
            "updated_ts = CURRENT_TIMESTAMP",
            (room_id, long_term_summary, objective_relations),
        )
        self.conn.commit()

    def load_summary(self, room_id: int) -> tuple[str, str]:
        row = self.conn.execute(
            "SELECT long_term_summary, objective_relations FROM summaries WHERE room_id = ?",
            (room_id,),
        ).fetchone()
        if row is None:
            return "", ""
        return row["long_term_summary"], row["objective_relations"]

    # ---- compose -------------------------------------------------------
    def load_room_state(self, room_id: int, history_limit: int | None = None) -> RoomState:
        """从库里拼出一个 RoomState（历史 + 记忆 + 摘要）。"""
        long_summary, relations = self.load_summary(room_id)
        return RoomState(
            long_term_summary=long_summary,
            objective_relations=relations,
            history=self.load_history(room_id, limit=history_limit),
            memory=self.load_memory(room_id),
        )
