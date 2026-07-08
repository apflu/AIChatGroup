"""会话结束检测器 —— M2 唯一要啃的新启发式（docs/milestone/M2.md §4）。

conductor 是 beat 级时钟的 owner；每拍（无论有人说还是留白）喂给 `EndDetector.observe`，
再 `check` 一次问"这段会话该收了吗、为什么"。**必须报 reason**——原因决定 storyteller 下一手。

"初版检测先土"：
- **lull**：连续 N 拍留白（conductor 返回 None）= 闲聊耗尽。
- **intent_fulfilled**：意图带 `length_budget` 且发言数跑满 = 达成。
- **deadlock**：张力高（`TensionReader` 读数 ≥ 阈值）且僵持够久 = 原地打转。
- **max_length**：总拍数超硬顶 = 兜底防拖死。
（`user_forced` 不在这里——它是 usher 的反应式事件，由 orchestrator 直接注入。）

张力来源被抽象成 `TensionReader`：默认 `FlatTensionReader` 恒 0 → **deadlock 关闭**（保守，
不误伤正常对话）；`StagnationTensionReader` 是零模型的结构启发式；M2-C 可换重模型读数。
检测器过急会把对话剁碎、过松会拖沓——是最该调的旋钮，故所有阈值都可配。
"""
from __future__ import annotations

from typing import Protocol

from ...domain.conversation import (
    DEADLOCK,
    INTENT_FULFILLED,
    LULL,
    MAX_LENGTH,
    ConversationEnd,
    ConversationIntent,
)
from ...domain.types import RoomState


class TensionReader(Protocol):
    def read(self, room: RoomState, intent: ConversationIntent | None) -> float:
        """返回当前张力读数（约定 0~1）。deadlock 判据的输入。"""
        ...


class FlatTensionReader:
    """恒 0 张力 —— deadlock 关闭。默认选它：宁可漏判僵局（下个边界 storyteller 兜底），
    也不误把正常对话判成僵局。"""

    def read(self, room: RoomState, intent: ConversationIntent | None) -> float:
        return 0.0


class StagnationTensionReader:
    """零模型的结构启发式：最近 `window` 拍只在 ≤2 个角色间反复交锋 → 高张力代理。

    "少数角色头对头、没人插得进"是"原地打转"最省的可观测信号。历史不足 window 时给冷读数
    （还没形成僵持）。M2-C 可用重 storyteller 的真张力读数替换本类。
    """

    def __init__(self, window: int = 6, hot: float = 0.8, cold: float = 0.2) -> None:
        self.window = window
        self.hot = hot
        self.cold = cold

    def read(self, room: RoomState, intent: ConversationIntent | None) -> float:
        recent = room.history[-self.window :]
        if len(recent) < self.window:
            return self.cold
        speakers = {m.speaker for m in recent}
        return self.hot if len(speakers) <= 2 else self.cold


class EndDetector:
    """跟踪一段会话的 beat 观测，判它该不该结束、报 reason。

    生命周期：每段会话开始 `begin(intent)` 重置；每拍 `observe(room, spoke)`；随后 `check(room)`。
    """

    def __init__(
        self,
        *,
        lull_patience: int = 2,
        max_beats: int = 30,
        deadlock_window: int = 6,
        deadlock_tension: float = 0.7,
        tension_reader: TensionReader | None = None,
    ) -> None:
        self.lull_patience = lull_patience
        self.max_beats = max_beats
        self.deadlock_window = deadlock_window
        self.deadlock_tension = deadlock_tension
        self.tension_reader: TensionReader = tension_reader or FlatTensionReader()
        self._intent: ConversationIntent | None = None
        self._beats = 0
        self._speeches = 0
        self._silence_run = 0
        self._stagnant_run = 0
        self._tension = 0.0

    def begin(self, intent: ConversationIntent | None) -> None:
        self._intent = intent
        self._beats = 0
        self._speeches = 0
        self._silence_run = 0
        self._stagnant_run = 0
        self._tension = 0.0

    def observe(self, room: RoomState, spoke: bool) -> None:
        """记录一拍：spoke=True 有人发言，False 表示 conductor 判这拍留白。"""
        self._beats += 1
        if spoke:
            self._speeches += 1
            self._silence_run = 0
            self._stagnant_run += 1     # 连续发言累加僵持
        else:
            self._silence_run += 1
            self._stagnant_run = 0       # 留白 = 喘息 = 打断僵持
        self._tension = self.tension_reader.read(room, self._intent)

    def check(self, room: RoomState) -> ConversationEnd | None:
        """返回 ConversationEnd（带 reason）或 None（会话继续）。优先级见函数体。"""
        # 1) 僵局最急：高张力 + 僵持够久 → 需 storyteller 打破
        if self._tension >= self.deadlock_tension and self._stagnant_run >= self.deadlock_window:
            return ConversationEnd(DEADLOCK, tension=self._tension)
        # 2) 意图达成：带预算的意图跑满发言数
        budget = self._intent.length_budget if self._intent else None
        if budget is not None and self._speeches >= budget:
            return ConversationEnd(INTENT_FULFILLED, tension=self._tension)
        # 3) 冷场：连续留白够久
        if self._silence_run >= self.lull_patience:
            return ConversationEnd(LULL, tension=self._tension)
        # 4) 超长硬兜底
        if self._beats >= self.max_beats:
            return ConversationEnd(MAX_LENGTH, tension=self._tension)
        return None
