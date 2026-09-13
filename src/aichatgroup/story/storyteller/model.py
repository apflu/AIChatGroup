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
from ...domain.types import Agent, RoomState
from ...io.gateway import ModelGateway, ask_or_none
from ...prompts import load as load_prompt
from ...prompts import render as render_prompt

logger = logging.getLogger(__name__)

# 输出契约标签（parser 据此抽 kind/hook/授知）。散文在 prompts/storyteller.system.md。
_KIND_LABEL = "KIND:"
_HOOK_LABEL = "HOOK:"
_KNOW_LABEL = "KNOW"     # `KNOW <agent_id>: <只有 ta 知道的事>`（M3 知识不对称，可 0~N 行）

_STORYTELLER_SYSTEM = load_prompt("storyteller/system")


class ModelStoryteller:
    def __init__(
        self, gateway: ModelGateway, model_id: str, recent_window: int = 16
    ) -> None:
        self.gateway = gateway
        self.model_id = model_id
        self.recent_window = recent_window

    def seed(
        self,
        room: RoomState,
        last_end: ConversationEnd | None,
        agents: list[Agent] | None = None,
    ) -> ConversationIntent:
        recent = "\n".join(m.render() for m in room.visible_history(last=self.recent_window))
        # 在场角色名册（name+id）进模板：storyteller 据此按 agent_id 私授知识；不给则无法定向授知。
        # 局势 = 长期摘要 + 客观关系（首段会话时这是 storyteller 唯一的"依据"）；兜底文案在模板里。
        user = render_prompt(
            "storyteller/user",
            summary=room.long_term_summary.strip(),
            relations=room.objective_relations.strip(),
            agents=agents or [],
            recent=recent,
            last_end=last_end,
        )
        # 网络/模型异常 → 保守回落闲聊（误判只赔平淡）
        resp = ask_or_none(
            self.gateway, self.model_id, _STORYTELLER_SYSTEM, user,
            max_tokens=256, source="storyteller",
        )
        if resp is None:
            return ConversationIntent(kind=CHITCHAT)
        return self._parse(resp.text)

    def _parse(self, text: str) -> ConversationIntent:
        kind = CHITCHAT
        hook_lines: list[str] = []
        knowledge: dict[str, str] = {}
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
            elif upper.startswith(_KNOW_LABEL + " "):
                # `KNOW <agent_id>: <知识>`——首个冒号切 id / 内容；id 合法性交 runtime 按名册筛
                body = stripped[len(_KNOW_LABEL) :].lstrip(" :")
                if ":" in body or "：" in body:
                    sep = ":" if ":" in body else "："
                    aid, _, know = body.partition(sep)
                    aid, know = aid.strip(), know.strip()
                    if aid and know:
                        knowledge[aid] = f"{knowledge[aid]} {know}".strip() if aid in knowledge else know
                collecting_hook = False
            elif collecting_hook and stripped:
                hook_lines.append(stripped)
        hook = " ".join(h for h in hook_lines if h).strip()
        return ConversationIntent(kind=kind, hook=hook, knowledge=knowledge)
