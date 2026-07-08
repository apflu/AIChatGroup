"""Usher —— 用户输入的台口分流（M2）。

站在台口，对每一条**用户输入**判一次：它需不需要「世界」做出回应？
- 不需要 → **absorb**：顺其自然，进共享历史，当前会话继续；下个会话边界 storyteller 自然看到。
- 需要   → **escalate**（`user_forced`：提前收束当前会话、唤醒 storyteller 播种回应用户的新意图），
           并附一个方向标签（advance / disrupt / probe / swerve = 推进 / 捣乱 / 试探 / 拐弯）。

判据是「世界要不要回应」，**不是「激不激进」**——破坏设定的话哪怕语气平静也要 escalate。
关键性质：**误判只赔延迟、不赔丢失**（被 absorb 的输入照样进历史，下个边界一定被 storyteller 看到），
所以默认**调保守**：模型异常 / 输出无法解析 → 一律 absorb。

设计详见 docs/milestone/M2.md §5。它坐在 message 平面、贴着 conductor：产出既可喂 conductor 的会话内
路由，又可喂 storyteller 的边界升级。M2-B 只做「判 + 出决策」，把 `user_forced` 接进会话状态机是 A 的事。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from ..domain.types import RoomState
from ..io.gateway import ModelGateway

logger = logging.getLogger(__name__)

# escalate 时的方向标签（推进 / 捣乱 / 试探 / 拐弯）
DIRECTIONS = ("advance", "disrupt", "probe", "swerve")
_ABSORB = "absorb"

_USHER_SYSTEM = (
    "你是群聊的引导者（usher），站在台口决定一条**用户输入**该怎么处理。"
    "判据只有一个：这句话需不需要「世界」做出回应——不是它激不激进、也不是礼不礼貌。"
    "普通闲聊、附和、不改变局面的话 → 输出 absorb。"
    "需要世界回应的话（推动剧情=advance、捣乱=disrupt、试探设定=probe、突然拐弯=swerve，"
    "或任何与世界设定冲突、哪怕语气平静的话）→ 输出对应的那个词。"
    "只输出 absorb / advance / disrupt / probe / swerve 之中的一个词，别的都不要。"
)


@dataclass
class UsherDecision:
    escalate: bool          # True → user_forced（提前收束会话、唤醒 storyteller）
    direction: str = ""     # escalate 时的方向：advance / disrupt / probe / swerve
    raw: str = ""           # 模型原始输出，便于日志 / 调试

    @property
    def absorb(self) -> bool:
        return not self.escalate


class Usher:
    """便宜模型判「用户输入要不要世界回应」，异常/噪声一律保守 absorb。"""

    def __init__(self, gateway: ModelGateway, model_id: str, recent_window: int = 8) -> None:
        self.gateway = gateway
        self.model_id = model_id
        self.recent_window = recent_window

    def classify(self, room: RoomState, text: str, speaker: str = "用户") -> UsherDecision:
        recent = "\n".join(
            m.render() for m in room.history[-self.recent_window :]
        ) or "（还没有人说话）"
        user = (
            f"# 最近对话\n{recent}\n\n"
            f"# 刚进来的用户输入\n[{speaker}] {text}\n\n"
            "这条用户输入需不需要世界回应？只输出一个词："
        )
        try:
            resp = self.gateway.complete(
                system=[{"type": "text", "text": _USHER_SYSTEM}],
                messages=[{"role": "user", "content": user}],
                model_id=self.model_id,
                max_tokens=8,
            )
            choice = resp.text.strip().lower()
        except Exception as exc:  # 网络/模型异常 → 保守 absorb（误判只赔延迟）
            logger.warning("usher 模型调用失败，保守 absorb：%s", exc)
            return UsherDecision(escalate=False, raw="")

        # 容忍噪声：取第一个命中的方向词或 absorb
        for token in choice.replace("，", " ").replace(",", " ").split():
            if token in DIRECTIONS:
                return UsherDecision(escalate=True, direction=token, raw=choice)
            if token == _ABSORB:
                return UsherDecision(escalate=False, raw=choice)
        # 无法解析 → 保守 absorb
        logger.debug("usher 输出无法解析(%r)，保守 absorb", choice)
        return UsherDecision(escalate=False, raw=choice)
