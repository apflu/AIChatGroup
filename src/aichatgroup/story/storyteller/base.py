"""Storyteller —— 会话级时钟的 owner（后台暗线平面）。

它**只在会话边界工作**（seed / reseed 两点），为下一段 conversation 播种 `ConversationIntent`，
交给 conductor 执行。不 mid-conversation 插手（那是轮询，重模型高频空转的根源）；
僵局 / 冷场 / 用户强制收束都统一走"会话自然结束 → 唤醒一次 → 播种下一段"。

两平面不变式：storyteller 的 agentic 复杂度（多步推理 / tool / sim 数值）留在暗线内部，
**只输出 `ConversationIntent`（domain 数据）**，不进前台消息流。意图的 `hook` 经 conductor 的
conductor_instruction 尾部（不缓存）槽注入 agent，不碰共享历史前缀 → 缓存不变式不破。
"""
from __future__ import annotations

from typing import Protocol

from ...domain.conversation import CHITCHAT, ConversationEnd, ConversationIntent
from ...domain.types import RoomState


class Storyteller(Protocol):
    def seed(
        self, room: RoomState, last_end: ConversationEnd | None
    ) -> ConversationIntent:
        """为下一段会话播种意图。last_end=None 表示这是本房间的第一段。"""
        ...


class StubStoryteller:
    """占位 storyteller（M2-A）：永远播种固定「闲聊」意图，behaviorally inert。

    让"会话边界"这个新结构在**完全不碰重模型**的前提下能被测通（seed→run→end→reseed）。
    M2-C 用 ModelStoryteller 替换它，才有真正的张力读数 / 世界抗拒 / 定向回应。
    """

    def __init__(self, kind: str = CHITCHAT, hook: str = "") -> None:
        self.kind = kind
        self.hook = hook

    def seed(
        self, room: RoomState, last_end: ConversationEnd | None
    ) -> ConversationIntent:
        return ConversationIntent(kind=self.kind, hook=self.hook)
