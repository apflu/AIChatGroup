"""ModelStoryteller —— 用重模型在会话边界播种意图（M2-C）。

只在边界跑（低频、重），读最近历史 + 上一段如何收束（`ConversationEnd.reason`），产出下一段的
`ConversationIntent`（kind + hook）。reason 决定它的下一手（M2.md §4 表）：
- lull → 抛新钩子 / 换话题；deadlock → 抛压力 / 转折 / 炸弹**打破**；
- user_forced → 把用户输入并进新意图（含世界抗拒：让世界抵抗/困惑，不替用户做决定）；
- intent_fulfilled / max_length → 收束进下一段。

输出契约（机器契约，留代码 + prompts/storyteller.system.md，test_prompts 防漂移）：
两行 `KIND: <kind>` / `HOOK: <一句悬着的压力>`。异常 / 无法解析 → 保守回落闲聊（误判只赔平淡）。
"""
from __future__ import annotations

import logging

from ...domain.conversation import (
    CHITCHAT,
    INTENT_KINDS,
    ConversationEnd,
    ConversationIntent,
)
from ...domain.types import RoomState
from ...io.gateway import ModelGateway
from ...observability import log_model_raw
from ...prompts import load as load_prompt, render as render_prompt

logger = logging.getLogger(__name__)

# 输出契约标签（parser 据此抽 kind/hook）。散文在 prompts/storyteller.system.md。
_KIND_LABEL = "KIND:"
_HOOK_LABEL = "HOOK:"

_STORYTELLER_SYSTEM = load_prompt("storyteller.system")


class ModelStoryteller:
    def __init__(
        self, gateway: ModelGateway, model_id: str, recent_window: int = 16
    ) -> None:
        self.gateway = gateway
        self.model_id = model_id
        self.recent_window = recent_window

    def seed(
        self, room: RoomState, last_end: ConversationEnd | None
    ) -> ConversationIntent:
        recent = "\n".join(
            m.render() for m in room.history[-self.recent_window :]
        ) or "（还没有人说话）"
        # 局势 = 长期摘要 + 客观关系（首段会话时这是 storyteller 唯一的"依据"，
        # 房间铺底的种子摘要经此进 storyteller 的决策，否则它只能看空历史瞎猜）
        situation_parts = []
        if room.long_term_summary.strip():
            situation_parts.append(room.long_term_summary.strip())
        if room.objective_relations.strip():
            situation_parts.append("关系：" + room.objective_relations.strip())
        situation = "\n".join(situation_parts) or "（暂无既有局势）"
        last_reason = last_end.reason if last_end else "（这是第一段会话）"
        last_summary = (last_end.summary_hook if last_end else "") or "（无）"
        direction = (last_end.direction if last_end else "") or "（无）"
        user = render_prompt(
            "storyteller.user",
            situation=situation,
            recent=recent,
            last_reason=last_reason,
            last_summary=last_summary,
            direction=direction,
        )
        try:
            resp = self.gateway.complete(
                system=[{"type": "text", "text": _STORYTELLER_SYSTEM}],
                messages=[{"role": "user", "content": user}],
                model_id=self.model_id,
                max_tokens=256,
            )
            log_model_raw("storyteller", resp.text)
            return self._parse(resp.text)
        except Exception as exc:  # 网络/模型异常 → 保守回落闲聊
            logger.warning("storyteller 模型调用失败，回落闲聊：%s", exc)
            return ConversationIntent(kind=CHITCHAT)

    def _parse(self, text: str) -> ConversationIntent:
        kind = CHITCHAT
        hook_lines: list[str] = []
        collecting_hook = False
        for line in text.splitlines():
            stripped = line.strip()
            upper = stripped.upper()
            if upper.startswith(_KIND_LABEL):
                token = stripped[len(_KIND_LABEL) :].strip().lower()
                if token in INTENT_KINDS:
                    kind = token
                collecting_hook = False
            elif upper.startswith(_HOOK_LABEL):
                hook_lines.append(stripped[len(_HOOK_LABEL) :].strip())
                collecting_hook = True     # HOOK 可跨多行
            elif collecting_hook and stripped:
                hook_lines.append(stripped)
        hook = " ".join(h for h in hook_lines if h).strip()
        return ConversationIntent(kind=kind, hook=hook)
