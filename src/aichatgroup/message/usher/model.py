"""Usher —— 用户输入的台口分流（M2）。

站在台口，对每一条**用户输入**判一次：它需不需要「世界」做出回应？
- 不需要 → **absorb**：顺其自然，进共享历史，当前会话继续；下个会话边界 storyteller 自然看到。
- 需要   → **escalate**（`user_forced`：提前收束当前会话、唤醒 storyteller 播种回应用户的新意图），
           并附一个方向标签（advance / disrupt / probe / swerve = 推进 / 捣乱 / 试探 / 拐弯）。

判据是「世界要不要回应」，**不是「激不激进」**——破坏设定的话哪怕语气平静也要 escalate。
误判代价**不对称**（曾写作"误判只赔延迟、不赔丢失"，那只在非 canon 输入上成立）：非 canon 误判赔延迟；
**canon 误判赔污染复利**——absorb 的破坏会被后续 beat 的 AI 放大成既成事实（详见 M2.md §9 的 §5×§9 耦合）。
默认**调保守**（模型异常 / 输出无法解析 → 一律 absorb）——回落层这个残余入口本期搁置、不动机制。

设计详见 docs/milestone/M2.md §5。它坐在 message 平面、贴着 conductor：产出既可喂 conductor 的会话内
路由，又可喂 storyteller 的边界升级。M2-B 只做「判 + 出决策」，把 `user_forced` 接进会话状态机是 A 的事。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from ...domain.types import RoomState
from ...io.gateway import ModelGateway, ask_or_none
from ...prompts import load as load_prompt
from ...prompts import render as render_prompt

logger = logging.getLogger(__name__)

# escalate 时的方向标签（推进 / 捣乱 / 试探 / 拐弯）。这是**机器契约**（parser 据此分流），
# 留在解析器身边；散文指令在 prompts/usher.system.md，test_prompts 断言这些词都出现在其中，防漂移。
DIRECTIONS = ("advance", "disrupt", "probe", "swerve")
_ABSORB = "absorb"
# canon 违规标记：与方向**正交**——模型在方向词后追加它，表示输入抵触已确立的世界设定。
# 只有它触发"世界回应后清洗"（M3 桥接）；合法强推（有方向、无 violate）照常 canon 化，不清洗。
VIOLATE_MARKER = "violate"

_USHER_SYSTEM = load_prompt("usher/system")


@dataclass
class UsherDecision:
    escalate: bool          # True → user_forced（提前收束会话、唤醒 storyteller）
    direction: str = ""     # escalate 时的方向：advance / disrupt / probe / swerve
    violation: bool = False  # 抵触世界 canon → 世界回应后应清洗（与 direction 正交）
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
        recent = "\n".join(m.render() for m in room.visible_history(last=self.recent_window))
        user = render_prompt("usher/user", recent=recent, speaker=speaker, text=text)
        # 网络/模型异常 → 保守 absorb（误判只赔延迟）
        resp = ask_or_none(
            self.gateway, self.model_id, _USHER_SYSTEM, user,
            max_tokens=12,          # 容两词：方向 + 可选的 violate 标记
            source="usher", speaker=speaker,
        )
        if resp is None:
            return UsherDecision(escalate=False, raw="")
        choice = resp.text.strip().lower()

        # violate 与方向正交，先整体扫一遍（否则方向词命中即返回会漏掉其后的 violate）
        tokens = choice.replace("，", " ").replace(",", " ").split()
        violation = VIOLATE_MARKER in tokens
        # 容忍噪声：取第一个命中的方向词或 absorb
        for token in tokens:
            if token in DIRECTIONS:
                return UsherDecision(
                    escalate=True, direction=token, violation=violation, raw=choice
                )
            if token == _ABSORB:
                return UsherDecision(escalate=False, raw=choice)
        if violation:
            # 只说了 violate 没给方向：canon 破坏本质是"捣乱"，默认 disrupt 兜底
            return UsherDecision(
                escalate=True, direction="disrupt", violation=True, raw=choice
            )
        # 无法解析 → 保守 absorb
        logger.debug("usher 输出无法解析(%r)，保守 absorb", choice)
        return UsherDecision(escalate=False, raw=choice)
