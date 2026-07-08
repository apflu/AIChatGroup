"""ModelConductor —— 用便宜模型（默认 Haiku）决定下一个说话者。

设计目标：让群聊「像真人」——不是死板轮流，而是谁被点到、谁有话说谁接。
但也要防刷屏：同一角色连说 max_consecutive 次后被强制排除。模型只在候选集里选，
或回 `none` 让场面留白（人类插话前的自然停顿）。

硬约束仍由规则兜底：模型给出非法/自选（刚说过话的人）时回退到第一个合法候选。
"""
from __future__ import annotations

import logging

from ...domain.types import Agent, RoomState
from ...io.gateway import ModelGateway
from ...prompts import load as load_prompt, render as render_prompt
from .base import consecutive_count, last_speaker_name

logger = logging.getLogger(__name__)

# 散文指令在 prompts/conductor.system.md；`none` 是机器契约（下方解析据它判留白），故此处仍显式处理。
_CONDUCTOR_SYSTEM = load_prompt("conductor.system")


class ModelConductor:
    def __init__(
        self,
        gateway: ModelGateway,
        model_id: str,
        recent_window: int = 12,
        max_consecutive: int = 2,
        allow_silence: bool = True,
    ) -> None:
        self.gateway = gateway
        self.model_id = model_id
        self.recent_window = recent_window
        self.max_consecutive = max_consecutive
        self.allow_silence = allow_silence

    def _eligible(self, room: RoomState, agents: list[Agent]) -> list[Agent]:
        last = last_speaker_name(room)
        elig = []
        for a in agents:
            # 刚说过话且已达连说上限 → 本拍排除，避免自言自语/刷屏
            if a.name == last and consecutive_count(room, a.name) >= self.max_consecutive:
                continue
            if a.name == last and self.max_consecutive <= 1:
                continue
            elig.append(a)
        return elig or agents

    def next_speaker(self, room: RoomState, agents: list[Agent]) -> str | None:
        eligible = self._eligible(room, agents)
        roster = "\n".join(f"- {a.id}：{a.name}" for a in eligible)
        recent = "\n".join(m.render() for m in room.history[-self.recent_window :]) or "(还没有人说话)"
        options = "、".join(a.id for a in eligible)
        hint = "，或 none" if self.allow_silence else ""
        user = render_prompt(
            "conductor.user", roster=roster, recent=recent, options=options, hint=hint
        )
        try:
            resp = self.gateway.complete(
                system=[{"type": "text", "text": _CONDUCTOR_SYSTEM}],
                messages=[{"role": "user", "content": user}],
                model_id=self.model_id,
                max_tokens=16,
            )
            choice = resp.text.strip().lower()
        except Exception as exc:  # 模型/网络异常 → 规则兜底
            logger.warning("conductor 模型调用失败，回退规则：%s", exc)
            choice = ""

        by_id = {a.id.lower(): a.id for a in eligible}
        if choice in ("none", "无", "留白") and self.allow_silence:
            return None
        # 容忍模型多输出——取第一个命中的 id
        for token in choice.replace("，", " ").replace(",", " ").split():
            if token in by_id:
                return by_id[token]
        if choice in by_id:
            return by_id[choice]
        # 非法输出 → 兜底选第一个合法候选
        logger.debug("conductor 输出无法解析(%r)，回退首个候选", choice)
        return eligible[0].id if eligible else None


# 迁移期别名：保住旧公共导出与外部引用，一个周期后可移除。
ModelDirector = ModelConductor
