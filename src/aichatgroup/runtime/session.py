"""ConversationSession —— 会话状态机（M2 三层嵌套时钟里的"会话级"那层）。

    storyteller.seed → ConversationIntent ──► 若干 beat（conductor 选人 + EndDetector 观测）
          ▲                                            │
          └──── reseed（last_end 带 reason）◄──── 会话收束（自然 / user_forced）──┘

它持有：当前意图、会话 DB 行（惰性建）、usher 置位的 user_forced、以及 M3 桥接的两级清洗队列
（pending → 回应后清洗）。Orchestrator 的 speak 循环只在三个点碰它：
`consume_forced_end()`（拍前）、`after_world_responded()`（成功发言后）、`observe_beat()`（拍后）。
"""
from __future__ import annotations

import logging

from ..domain.conversation import ConversationEnd, ConversationIntent
from ..domain.types import Agent
from ..io.persistence.room_repo import RoomRepository
from ..message.conductor.end_detector import EndDetector
from ..observability import log_event
from ..story.storyteller import Storyteller, merge_knowledge

logger = logging.getLogger(__name__)


class ConversationSession:
    def __init__(
        self,
        storyteller: Storyteller,
        detector: EndDetector,
        repo: RoomRepository,
        agents: list[Agent],
    ) -> None:
        self.storyteller = storyteller
        self.detector = detector
        self.repo = repo
        self.agents = agents
        self._agent_ids = {a.id for a in agents}

        self.intent: ConversationIntent | None = None
        self.conv_id: int | None = None            # 当前会话 DB 行；惰性建（首个气泡时）
        self.forced_end: ConversationEnd | None = None   # usher escalate 置位，循环消费
        # usher 判违规（canon 破坏）的输入 id：摄入处入队，forced_end 消费时转入
        # redact_after_response，等世界抗拒会话**首次成功回应之后**再清洗——回应期间它仍在
        # 历史里供世界有据地抗拒，回应后消失，斩断后续 beat 的放大链（M3 桥接）。
        self.pending_redaction: list[int] = []
        self.redact_after_response: list[int] = []

    @property
    def hook(self) -> str:
        return self.intent.hook if self.intent else ""

    # ---- 边界：seed / end ------------------------------------------------
    def begin(self, last_end: ConversationEnd | None = None) -> None:
        """seed / reseed：storyteller 为下一段会话播种意图，重置结束检测器。"""
        self.intent = self.storyteller.seed(self.repo.room, last_end, self.agents)
        self._apply_knowledge_grants(self.intent)
        self.conv_id = None
        self.detector.begin(self.intent)
        log_event(
            "conversation_seed",
            intent_kind=self.intent.kind,
            hook=self.intent.hook,
            last_reason=(last_end.reason if last_end else None),
        )

    def _apply_knowledge_grants(self, intent: ConversationIntent) -> None:
        """storyteller 私授的知识累积进 room.knowledge[agent_id] + 持久化（M3 知识不对称）。
        只认名册里的 agent_id（模型瞎报的 id 丢弃）；累积去重；进不缓存尾部，缓存安全。"""
        for agent_id, grant in intent.knowledge.items():
            if agent_id not in self._agent_ids or not grant.strip():
                continue
            merged = merge_knowledge(self.repo.room.knowledge.get(agent_id, ""), grant)
            self.repo.save_knowledge(agent_id, merged)
            log_event("knowledge_grant", agent=agent_id)

    def ensure_row(self) -> int | None:
        """首个气泡时才把会话落库——空会话（冷场即散）不留垃圾行。"""
        if self.conv_id is None and self.intent is not None:
            self.conv_id = self.repo.start_conversation(self.intent.kind, self.intent.hook)
        return self.conv_id

    def end(self, end: ConversationEnd) -> None:
        self.repo.end_conversation(
            self.conv_id, reason=end.reason, tension=end.tension, summary=end.summary_hook
        )
        log_event("conversation_end", reason=end.reason, tension=end.tension, conv_id=self.conv_id)

    # ---- user_forced（usher 台口 → 循环消费）------------------------------
    def force_end(self, end: ConversationEnd, *, redact_id: int | None = None) -> None:
        """usher escalate：置位 user_forced；违规输入 id 入队待清洗。"""
        self.forced_end = end
        if redact_id is not None:
            self.pending_redaction.append(redact_id)

    def consume_forced_end(self) -> ConversationEnd | None:
        """若有 user_forced：走同一条边界交接路径（end → reseed），并把待清洗 id 转入"回应后"队列。
        返回被消费的 end（None = 本拍无强制收束）。"""
        forced = self.forced_end
        if forced is None:
            return None
        self.forced_end = None
        self.end(forced)
        self.begin(last_end=forced)
        # 违规输入随抗拒会话开场进入"待回应后清洗"队列：此刻还不动它，
        # 让接下来的世界抗拒回应能读到它、有据地抵抗；回应成功后再清洗。
        if self.pending_redaction:
            self.redact_after_response.extend(self.pending_redaction)
            self.pending_redaction = []
        return forced

    def after_world_responded(self) -> None:
        """世界成功回应之后：清洗排队的违规输入（软删除，对所有 agent 的上下文不可见）。"""
        for mid in self.redact_after_response:
            self.repo.redact(mid)
            logger.info("清洗违规输入 ⟦%s⟧", mid)
            log_event("usher_cleanse", msg_id=mid)
        self.redact_after_response = []

    # ---- beat 观测 → 自然收束 ------------------------------------------
    def observe_beat(self, spoke: bool) -> ConversationEnd | None:
        """每拍喂检测器；会话该收则 end + reseed，返回 end（None = 继续）。"""
        self.detector.observe(self.repo.room, spoke)
        end = self.detector.check(self.repo.room)
        if end is not None:
            self.end(end)
            self.begin(last_end=end)
        return end
