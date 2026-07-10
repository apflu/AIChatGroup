"""Orchestrator —— transport-agnostic 的会话主循环。

把摄入、调度、发言、发送、持久化、开关键、compaction 串成一个异步循环。
它不认识 Telegram；只依赖 Transport / Conductor / Storyteller / Store 抽象。

M2：循环从"每拍 conductor 选人"升级为**会话状态机**（三层嵌套时钟，见 docs/milestone/M2.md）：

    storyteller.seed → ConversationIntent ──► 若干 beat（conductor 选人 + EndDetector 观测）
          ▲                                            │
          └──── reseed（last_end 带 reason）◄──── conductor 检测到会话收束 ──┘

- **storyteller**（会话级时钟）只在边界工作：seed / reseed。意图的 hook 经 conductor_instruction
  尾部（不缓存）槽注入 agent，不碰共享历史前缀 → 缓存不变式不破。
- **conductor**（beat 级时钟）：每拍选人；EndDetector 依 beat 观测判会话该不该结束、报 reason。
- **usher**：用户输入台口分流。escalate → `user_forced` → 提前收束当前会话，走同一条边界交接路径。

并发模型（要点）：
- 两个协程共享一份 RoomState：`_ingest_loop`（摄入人类/外部消息 + usher 分流）与
  `_speak_loop`（驱动会话）。二者都只在**事件循环线程**里读写 room。
- 唯一下放到线程池（to_thread）的是**发言的网络调用** `gateway.complete`——它不碰 room。
- conductor / storyteller / usher / compaction 的模型调用为简洁起见同步执行（便宜、低频），
  会短暂占用循环；MVP 可接受。storyteller 只在会话边界跑（事件驱动，非每拍轮询）。
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Awaitable, Callable

from ..domain.conversation import USER_FORCED, ConversationEnd, ConversationIntent
from ..domain.player import STRANGER_NAME
from ..domain.types import Agent, RoomState, WorldBook
from .players import PlayerRegistry
from ..io.gateway import ModelGateway
from ..io.persistence.store import Store
from ..io.transport.base import InboundMessage, Transport
from ..message.conductor.base import Conductor
from ..message.conductor.end_detector import EndDetector
from ..message.delivery.pacing import resolve_pauses
from ..message.generator.parsing import parse_turn_output
from ..message.generator.turn import merge_memory
from ..message.prompt import build_prompt
from ..message.usher import Usher
from ..observability import log_event, log_model_raw
from ..story.memory.compaction import maybe_compact
from ..story.storyteller import Storyteller, StubStoryteller
from .switch import MasterSwitch

logger = logging.getLogger(__name__)

_COMMANDS = {"/pause", "/resume", "/status", "/stop"}


class Orchestrator:
    def __init__(
        self,
        world: WorldBook,
        agents: list[Agent],
        gateway: ModelGateway,
        conductor: Conductor | None = None,
        transport: Transport | None = None,
        *,
        director: Conductor | None = None,   # 迁移期别名：等价 conductor
        storyteller: Storyteller | None = None,
        usher: Usher | None = None,
        players: PlayerRegistry | None = None,
        end_detector: EndDetector | None = None,
        room: RoomState | None = None,
        store: Store | None = None,
        room_key: str = "default",
        switch: MasterSwitch | None = None,
        max_tokens: int = 1024,
        turn_interval_s: float = 1.5,
        idle_poll_s: float = 2.0,
        compaction_model_id: str | None = None,
        max_history: int = 60,
        keep_last: int = 20,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.world = world
        self.agents = agents
        self._agent_by_id = {a.id: a for a in agents}
        self.gateway = gateway
        self.conductor = conductor if conductor is not None else director
        if self.conductor is None:
            raise TypeError("Orchestrator 需要 conductor（或迁移期别名 director）")
        self.transport = transport
        self.storyteller: Storyteller = storyteller or StubStoryteller()
        self.usher = usher
        self.players = players
        self.detector = end_detector or EndDetector()
        self.store = store
        self.switch = switch or MasterSwitch()
        self.max_tokens = max_tokens
        self.turn_interval_s = turn_interval_s
        self.idle_poll_s = idle_poll_s
        self.compaction_model_id = compaction_model_id
        self.max_history = max_history
        self.keep_last = keep_last
        self._sleep = sleep

        self.room_id: int | None = None
        if store is not None:
            self.room_id = store.ensure_room(room_key)
            self.room = room or store.load_room_state(self.room_id)
        else:
            self.room = room or RoomState()

        # 会话状态机的当前状态
        self._intent: ConversationIntent | None = None
        self._conv_id: int | None = None          # 当前会话 DB 行；惰性建（首个气泡时）
        self._forced_end: ConversationEnd | None = None   # usher escalate 置位，循环消费

        self._running = False
        self._stop_event = asyncio.Event()

    # ---- director 别名（读旧属性名的外部代码兼容）----------------------
    @property
    def director(self) -> Conductor:
        return self.conductor

    # ---- 生命周期 ------------------------------------------------------
    async def run(self, max_turns: int | None = None) -> int:
        """启动主循环。max_turns 非空时跑满该发言回合数后自动停（测试/演示用）。

        返回实际完成的发言回合数。
        """
        await self.transport.start()
        self._running = True
        self._stop_event.clear()
        ingest = asyncio.create_task(self._ingest_loop())
        try:
            turns = await self._speak_loop(max_turns)
        finally:
            self._running = False
            ingest.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await ingest
            await self.transport.stop()
        return turns

    def request_stop(self) -> None:
        self._running = False
        self._stop_event.set()

    # ---- 会话状态机 ----------------------------------------------------
    def _begin_conversation(self, last_end: ConversationEnd | None = None) -> None:
        """seed / reseed：storyteller 为下一段会话播种意图，重置结束检测器。"""
        self._intent = self.storyteller.seed(self.room, last_end)
        self._conv_id = None                       # 惰性建表：首个气泡时才落库
        self.detector.begin(self._intent)
        log_event(
            "conversation_seed",
            intent_kind=self._intent.kind,
            hook=self._intent.hook,
            last_reason=(last_end.reason if last_end else None),
        )

    def _ensure_conversation_row(self) -> int | None:
        """首个气泡时才把会话落库——空会话（冷场即散）不留垃圾行。"""
        if (
            self._conv_id is None
            and self.store is not None
            and self.room_id is not None
            and self._intent is not None
        ):
            self._conv_id = self.store.start_conversation(
                self.room_id, kind=self._intent.kind, hook=self._intent.hook
            )
        return self._conv_id

    def _end_conversation(self, end: ConversationEnd) -> None:
        if self._conv_id is not None and self.store is not None:
            self.store.end_conversation(
                self._conv_id,
                reason=end.reason,
                tension=end.tension,
                summary=end.summary_hook,
            )
        log_event(
            "conversation_end", reason=end.reason, tension=end.tension, conv_id=self._conv_id
        )

    # ---- 摄入 ----------------------------------------------------------
    async def _ingest_loop(self) -> None:
        while self._running:
            msg = await self.transport.next_inbound()
            self._handle_inbound(msg)

    def _handle_inbound(self, msg: InboundMessage) -> None:
        text = msg.text.strip()
        first = text.split(" ", 1)[0].lower()
        if first == "/iam":
            self._handle_iam(msg)              # 认领世界名，需 sender_id，故走这条特殊路
            return
        if msg.is_command or first in _COMMANDS:
            self._handle_command(text)
            return
        # 解析世界身份：稳定 sender_id → Player 世界名（未注册=陌生人；无注册表=原显示名）
        speaker = self._resolve_speaker(msg)
        # 若这条是回复某条消息，把被回复的 external_id 解析成内部 id
        reply_to = self._internal_id_for_external(msg.reply_to_external_id)
        # 去重 + 追加共享历史（store id 为权威 handle）
        mid = None
        if self.store is not None and self.room_id is not None:
            mid = self.store.append_message(
                self.room_id, speaker, msg.text,
                external_id=msg.external_id, reply_to_id=reply_to,
                conversation_id=self._conv_id,
            )
            if mid is None:
                logger.debug("摄入去重：external_id=%s 已存在，跳过", msg.external_id)
                return
        meta = {"external_id": msg.external_id} if msg.external_id else None
        self.room.append(
            speaker, msg.text, id=mid, author_kind="human",
            reply_to=reply_to, meta=meta,
        )
        logger.info("摄入 [%s] %s", speaker, msg.text)
        log_event("ingest", speaker=speaker, msg_id=mid, reply_to=reply_to)
        self._triage_user_input(msg, speaker)

    def _resolve_speaker(self, msg: InboundMessage) -> str:
        """把发送者解析成世界内显示名。无注册表→原显示名（旧行为）；有表但未注册→陌生人。"""
        if self.players is not None and msg.sender_id:
            player = self.players.resolve(msg.channel or "telegram", msg.sender_id)
            return player.name if player is not None else STRANGER_NAME
        return msg.speaker

    def _handle_iam(self, msg: InboundMessage) -> None:
        """`/iam <世界名>`：把发送者的稳定 id 绑到一个世界名（含净化/软查重）。"""
        if self.players is None or not msg.sender_id:
            return
        parts = msg.text.split(" ", 1)
        name = parts[1].strip() if len(parts) > 1 else ""
        channel = msg.channel or "telegram"
        if not name:
            log_event("player_iam_rejected", channel=channel, reason="空名字")
            return
        try:
            player = self.players.register(channel, msg.sender_id, name)
        except ValueError as exc:
            log_event("player_iam_rejected", channel=channel, name=name, reason=str(exc))
            return
        logger.info("玩家认领世界名：%s", player.name)
        log_event("player_register", name=player.name, channel=channel)

    def _triage_user_input(self, msg: InboundMessage, speaker: str) -> None:
        """usher 台口分流：escalate → 置 user_forced，让 speak 循环提前收束当前会话。

        误判只赔延迟不赔丢失——absorb 的输入已进历史，下个边界 storyteller 一定看到。
        speaker 是解析后的世界名（usher 也据世界身份判断，而非原始显示名）。
        """
        if self.usher is None:
            return
        decision = self.usher.classify(self.room, msg.text, speaker=speaker)
        if decision.escalate:
            self._forced_end = ConversationEnd(
                reason=USER_FORCED, summary_hook=msg.text, direction=decision.direction
            )
            log_event("usher_escalate", speaker=speaker, direction=decision.direction)
        else:
            log_event("usher_absorb", speaker=speaker)

    # ---- 回复寻址辅助 --------------------------------------------------
    def _internal_id_for_external(self, external_id: str | None) -> int | None:
        if external_id is None:
            return None
        if self.store is not None and self.room_id is not None:
            return self.store.id_for_external(self.room_id, external_id)
        for m in reversed(self.room.history):        # 离线：扫近窗
            if m.meta.get("external_id") == external_id:
                return m.id
        return None

    def _external_for_internal_id(self, mid: int | None) -> str | None:
        if mid is None:
            return None
        for m in reversed(self.room.history):        # 近窗优先
            if m.id == mid:
                return m.meta.get("external_id")
        if self.store is not None and self.room_id is not None:
            t = self.store.get_message(self.room_id, mid)
            return t.meta.get("external_id") if t is not None else None
        return None

    def _resolve_message(self, mid: int):
        if self.store is not None and self.room_id is not None:
            return self.store.get_message(self.room_id, mid)
        for m in self.room.history:
            if m.id == mid:
                return m
        return None

    def _handle_command(self, text: str) -> None:
        cmd = text.split(" ", 1)[0].lower()
        if cmd == "/pause":
            self.switch.pause()
            logger.info("开关：已暂停自动 chatter")
        elif cmd == "/resume":
            self.switch.resume()
            logger.info("开关：已恢复自动 chatter")
        elif cmd == "/status":
            logger.info("开关状态：%s", "暂停" if self.switch.paused else "运行")
        elif cmd == "/stop":
            logger.info("收到 /stop，准备停机")
            self.request_stop()

    # ---- 发言（会话循环）----------------------------------------------
    async def _speak_loop(self, max_turns: int | None) -> int:
        turns = 0
        self._begin_conversation()                   # 播种第一段会话
        while self._running:
            if max_turns is not None and turns >= max_turns:
                break
            if self.switch.paused:
                await self._sleep(self.idle_poll_s)
                continue

            # 用户强制收束优先：提前触发一次正常的边界交接（机制与自然结束统一）
            forced = self._forced_end
            if forced is not None:
                self._forced_end = None
                self._end_conversation(forced)
                self._begin_conversation(last_end=forced)
                continue

            speaker_id = self.conductor.next_speaker(self.room, self.agents)
            spoke = speaker_id is not None and speaker_id in self._agent_by_id
            if spoke:
                agent = self._agent_by_id[speaker_id]
                log_event("schedule", agent=agent.name, model=agent.model_id)
                hook = self._intent.hook if self._intent else ""
                try:
                    await self._speak(agent, hook)
                except Exception as exc:
                    # 单个 provider 抽风（鉴权失败/超时/限流）不应拖垮整屋子。
                    logger.exception("角色 %s 发言失败，跳过本回合", agent.name)
                    log_event("error", agent=agent.name, error=str(exc))
                turns += 1

            # beat 观测 → 会话是否收束（带 reason）
            self.detector.observe(self.room, spoke)
            end = self.detector.check(self.room)
            if end is not None:
                self._end_conversation(end)
                self._begin_conversation(last_end=end)

            if spoke:
                await self._maybe_compact()
                await self._sleep(self.turn_interval_s)
            elif end is None:
                # 这一拍留白且未到 lull：等人插话，别空转
                await self._sleep(self.idle_poll_s)
        return turns

    async def _speak(self, agent: Agent, conductor_instruction: str = "") -> None:
        conv_id = self._ensure_conversation_row()
        # 1) 组装 prompt（循环线程内，只读 room）；resolve 供超窗回复内联重注入
        system, messages = build_prompt(
            self.world, self.room, agent, conductor_instruction,
            resolve=self._resolve_message,
        )
        # 2) 网络调用下放线程池（不碰 room，无竞争）
        resp = await asyncio.to_thread(
            self.gateway.complete, system, messages, agent.model_id, self.max_tokens
        )
        # 3) 解析 + 节奏（循环线程内）
        # 原始模型输出先落 FIREHOSE（解析前），便于诊断"回复未命中 filter"/prompt 效果
        log_model_raw("generator", resp.text, agent=agent.name)
        parsed, memory_delta = parse_turn_output(resp.text, speaker=agent.name)
        # 停顿按**台词**长度算（动作已剥离、不由角色 bot 打字）；纯举动气泡台词为空、停顿退到基础值
        pauses = resolve_pauses(
            [pb.text for pb in parsed], [pb.pause_hint for pb in parsed], agent.pacing
        )
        logger.info(
            "回合 %s bubbles=%d cache_read=%d cache_creation=%d",
            agent.name, len(parsed),
            resp.usage.cache_read_input_tokens, resp.usage.cache_creation_input_tokens,
        )
        # model_call 只留 output + cache 计数（不记 input tokens），TRACE 级保持可读、够诊断 cache
        log_event(
            "model_call", agent=agent.name, model=agent.model_id, bubbles=len(parsed),
            output_tokens=resp.usage.output_tokens,
            cache_read=resp.usage.cache_read_input_tokens,
            cache_creation=resp.usage.cache_creation_input_tokens,
        )
        # 4) 逐条发送，按 kind 分流投递（两平面：舞台层不由角色第一人称括号发）：
        #    举动(beat) → 旁白 bot 0 第三人称播报；神态(gesture) → 隐去；台词(speech) → 角色 bot。
        #    历史/持久化仍存完整 display（含动作括号）→ 模型上下文与共享缓存前缀不变。
        for pb, pause in zip(parsed, pauses):
            # 举动先由旁白公之于众（多数是「先动手、再开口」）
            for beat in pb.beats:
                await self.transport.send_system(f"{agent.name}{beat}")
            # 台词 → 角色 bot（纯举动气泡台词为空则不发，但仍入历史保留动作）
            speech = pb.text
            ext = None
            if speech.strip():
                await self.transport.send_typing(agent)
                if pause > 0:
                    await self._sleep(pause)
                # 若这条回复了历史某条，解析出被回复消息的 external_id 一起发给 transport
                target_ext = self._external_for_internal_id(pb.reply_to)
                ext = await self.transport.send_text(
                    agent, speech, reply_to_external_id=target_ext
                )
            # store id 为权威 handle；回填 external_id（供后续消息回复本条）+ reply_to_id
            mid = None
            if self.store is not None and self.room_id is not None:
                mid = self.store.append_message(
                    self.room_id, agent.name, pb.display,
                    external_id=ext, reply_to_id=pb.reply_to,
                    conversation_id=conv_id,
                )
            meta = {"external_id": ext} if ext else None
            self.room.append(
                agent.name, id=mid, parts=pb.parts, reply_to=pb.reply_to, meta=meta,
            )
        # 5) 合并记忆增量（尾部私有快照，不缓存）
        if memory_delta:
            merged = merge_memory(self.room.memory.get(agent.id, ""), memory_delta)
            self.room.memory[agent.id] = merged
            if self.store is not None and self.room_id is not None:
                self.store.save_memory(self.room_id, agent.id, merged)

    async def _maybe_compact(self) -> None:
        if self.compaction_model_id is None:
            return
        result = maybe_compact(
            self.gateway, self.world, self.room, self.compaction_model_id,
            max_history=self.max_history, keep_last=self.keep_last, max_tokens=self.max_tokens,
        )
        if result.compacted:
            log_event("compaction", dropped=result.dropped)
            if self.store is not None and self.room_id is not None:
                self.store.save_summary(
                    self.room_id, self.room.long_term_summary, self.room.objective_relations
                )
                self.store.trim_history(self.room_id, self.keep_last)
