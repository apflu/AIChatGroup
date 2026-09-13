"""RoomRepository —— 内存近窗（RoomState）+ 可选持久层（Store）的**唯一**写入口。

Orchestrator 之前每次改状态都要写两遍（`room.xxx` + `if store: store.xxx`），八处相同的守卫。
收进这里后调用方只写一次；离线（无 store）与在线（有 store）的差别也只在这一个类里体现：
- id 铸造：有 store 时 messages.id 是权威 handle；离线由 RoomState 计数器给。
- 回复寻址：external_id ↔ 内部 id 的解析，有 store 查库、离线扫近窗。
- 超窗取回：`find(mid)` 有 store 可取回已滑出近窗的消息（builder 内联重注入用）。

它不做业务判断（谁可见、要不要清洗），只负责"一致地写两边"。
"""
from __future__ import annotations

from ...domain.types import ContentPart, Message, RoomState
from .store import Store


class RoomRepository:
    def __init__(
        self,
        room: RoomState,
        store: Store | None = None,
        room_id: int | None = None,
    ) -> None:
        self.room = room
        self.store = store
        self.room_id = room_id

    # ---- 构造 ----------------------------------------------------------
    @classmethod
    def open(
        cls, store: Store, room_key: str, *, history_limit: int, room: RoomState | None = None
    ) -> RoomRepository:
        """有持久层：确保房间存在，并只把**近窗**灌进内存（全量会让模型回复上次运行的失效 id）。"""
        room_id = store.ensure_room(room_key)
        state = room or store.load_room_state(room_id, history_limit=history_limit)
        return cls(state, store, room_id)

    @classmethod
    def in_memory(cls, room: RoomState | None = None) -> RoomRepository:
        return cls(room or RoomState())

    @property
    def persistent(self) -> bool:
        return self.store is not None and self.room_id is not None

    # ---- 消息 ----------------------------------------------------------
    def append_human(
        self,
        speaker: str,
        text: str,
        *,
        external_id: str | None = None,
        reply_to: int | None = None,
        conversation_id: int | None = None,
    ) -> Message | None:
        """摄入一条外部消息。按 external_id 去重：重复时返回 None、两边都不写。"""
        mid = None
        if self.persistent:
            mid = self.store.append_message(
                self.room_id, speaker, text,
                external_id=external_id, reply_to_id=reply_to, conversation_id=conversation_id,
            )
            if mid is None:
                return None
        meta = {"external_id": external_id} if external_id else None
        return self.room.append(
            speaker, text, id=mid, author_kind="human", reply_to=reply_to, meta=meta,
        )

    def append_bubble(
        self,
        speaker: str,
        parts: list[ContentPart],
        display: str,
        *,
        external_id: str | None = None,
        reply_to: int | None = None,
        conversation_id: int | None = None,
    ) -> Message:
        """角色气泡入史：持久化存完整 display（含动作括号），内存存 parts。"""
        mid = None
        if self.persistent:
            mid = self.store.append_message(
                self.room_id, speaker, display,
                external_id=external_id, reply_to_id=reply_to, conversation_id=conversation_id,
            )
        meta = {"external_id": external_id} if external_id else None
        return self.room.append(speaker, id=mid, parts=parts, reply_to=reply_to, meta=meta)

    def id_for_external(self, external_id: str | None) -> int | None:
        if external_id is None:
            return None
        if self.persistent:
            return self.store.id_for_external(self.room_id, external_id)
        for m in reversed(self.room.history):
            if m.meta.get("external_id") == external_id:
                return m.id
        return None

    def in_window(self, mid: int | None) -> Message | None:
        """只在**近窗**里找——超窗刻意返回 None（其 external_id 多已失效，见 delivery 的回复寻址）。"""
        if mid is None:
            return None
        for m in reversed(self.room.history):
            if m.id == mid:
                return m
        return None

    def find(self, mid: int) -> Message | None:
        """按内部 id 取消息，可取回已滑出近窗的（builder 超窗内联重注入用）。"""
        if self.persistent:
            return self.store.get_message(self.room_id, mid)
        return self.in_window(mid)

    def redact(self, mid: int) -> None:
        """软删除：对所有 agent 的模型上下文不可见。库行保留（审计），内存同步置位。"""
        if self.persistent:
            self.store.redact_message(self.room_id, mid)
        m = self.in_window(mid)
        if m is not None:
            m.redacted = True

    # ---- 每角色尾部快照 --------------------------------------------------
    def save_memory(self, agent_id: str, content: str) -> None:
        self.room.memory[agent_id] = content
        if self.persistent:
            self.store.save_memory(self.room_id, agent_id, content)

    def save_knowledge(self, agent_id: str, content: str) -> None:
        self.room.knowledge[agent_id] = content
        if self.persistent:
            self.store.save_knowledge(self.room_id, agent_id, content)

    # ---- 会话（M2）--------------------------------------------------------
    def start_conversation(self, kind: str, hook: str) -> int | None:
        if not self.persistent:
            return None
        return self.store.start_conversation(self.room_id, kind=kind, hook=hook)

    def end_conversation(
        self, conversation_id: int | None, *, reason: str, tension: float, summary: str
    ) -> None:
        if conversation_id is None or not self.persistent:
            return
        self.store.end_conversation(
            conversation_id, reason=reason, tension=tension, summary=summary
        )

    # ---- compaction ----------------------------------------------------
    def persist_compaction(self, keep_last: int) -> None:
        """compaction 就地改了 room 之后：写摘要 + 裁库里的历史。"""
        if not self.persistent:
            return
        self.store.save_summary(
            self.room_id, self.room.long_term_summary, self.room.objective_relations
        )
        self.store.trim_history(self.room_id, keep_last)
