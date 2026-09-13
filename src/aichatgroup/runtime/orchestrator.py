"""Orchestrator —— transport-agnostic 的会话主循环（只接线 + loop，不再是 god-loop）。

它不认识 Telegram；只依赖 Transport / Conductor / Storyteller / Store 抽象，把各段接起来：

    摄入：transport.next_inbound → 指令分派 | 身份解析(players) → repo 入史 → usher 分流 → session
    发言：session 边界交接 → conductor 选人 → generator（prepare/complete/finish）
          → delivery 队列（逐条投递、逐条经 repo 入史）→ 记忆合并 → 回应后清洗 → compaction
    抢占：usher escalate = "关键打断" → `interrupt()`：清掉当前 beat 未发的气泡（在飞的生成跑完即弃），
          同时 user_forced 让下一拍立刻 reseed 一段回应用户的会话（docs/message-ordering.md §7）

各段的归属（见 docs/architecture.md）：
- 会话状态机（seed/end/user_forced/清洗队列）在 `runtime/session.py`；
- 内存近窗 + 持久层的一致写在 `io/persistence/room_repo.py`；
- 生成在 `message/generator/turn.py`，演出（含单消费者队列与抢占）在 `message/delivery/`；
- 平台 reply 限制在各 transport 的 `can_reply_natively`。

并发模型（要点）：
- 两个协程共享一份 RoomState：`_ingest_loop` 与 `_speak_loop`。二者都只在**事件循环线程**里读写 room。
- 唯一下放到线程池（to_thread）的是**发言的网络调用** `gateway.complete`——它不碰 room。
- conductor / storyteller / usher / compaction 的模型调用为简洁起见同步执行（便宜、低频），
  会短暂占用循环；MVP 可接受。storyteller 只在会话边界跑（事件驱动，非每拍轮询）。
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

from ..domain.commands import IAM, PAUSE, RESUME, STATUS, STOP, command_word, is_command
from ..domain.conversation import USER_FORCED, ConversationEnd
from ..domain.types import Agent, RoomState, WorldBook
from ..io.gateway import ModelGateway
from ..io.persistence.room_repo import RoomRepository
from ..io.persistence.store import Store
from ..io.transport.base import InboundMessage, Transport
from ..message.conductor.base import Conductor
from ..message.conductor.end_detector import EndDetector
from ..message.delivery import DeliveryQueue, perform_queue
from ..message.generator.parsing import ParsedBubble
from ..message.generator.turn import finish_turn, merge_memory, prepare_turn
from ..message.usher import Usher
from ..observability import log_event
from ..story.memory.compaction import maybe_compact
from ..story.storyteller import Storyteller, StubStoryteller
from .players import PlayerRegistry, claim_name, resolve_speaker
from .session import ConversationSession
from .switch import MasterSwitch

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(
        self,
        world: WorldBook,
        agents: list[Agent],
        gateway: ModelGateway,
        conductor: Conductor,
        transport: Transport,
        *,
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
        self.conductor = conductor
        self.transport = transport
        self.usher = usher
        self.players = players
        self.switch = switch or MasterSwitch()
        self.max_tokens = max_tokens
        self.turn_interval_s = turn_interval_s
        self.idle_poll_s = idle_poll_s
        self.compaction_model_id = compaction_model_id
        self.max_history = max_history
        self.keep_last = keep_last
        self._sleep = sleep

        if store is not None:
            self.repo = RoomRepository.open(store, room_key, history_limit=max_history, room=room)
        else:
            self.repo = RoomRepository.in_memory(room)
        self.session = ConversationSession(
            storyteller or StubStoryteller(), end_detector or EndDetector(), self.repo, agents
        )

        self.delivery = DeliveryQueue()              # 单消费者：只在循环线程里入队/出队/抢占

        self._running = False
        self._stop_event = asyncio.Event()

    # 便利属性（脚本/测试读）
    @property
    def room(self) -> RoomState:
        return self.repo.room

    @property
    def store(self) -> Store | None:
        return self.repo.store

    @property
    def room_id(self) -> int | None:
        return self.repo.room_id

    # ---- 生命周期 ------------------------------------------------------
    async def run(self, max_turns: int | None = None) -> int:
        """启动主循环。max_turns 非空时跑满该发言回合数后自动停（测试/演示用）。返回实际完成的发言回合数。"""
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

    def interrupt(self, reason: str = "user") -> int:
        """打断 / 重规划的唯一触发口（用户关键打断、将来 storyteller 抛压力都走这里）。

        清掉当前 beat 尚未发出的气泡；在飞的生成回来后凭 beat 戳自弃。返回丢弃的气泡数。
        谁来规划下一拍不归它管——调用方另行置位（用户路径是 session.force_end）。
        """
        dropped = self.delivery.abort(reason=reason)
        log_event("interrupt", reason=reason, dropped=dropped)
        return dropped

    # ---- 摄入 ----------------------------------------------------------
    async def _ingest_loop(self) -> None:
        while self._running:
            msg = await self.transport.next_inbound()
            self._handle_inbound(msg)

    def _handle_inbound(self, msg: InboundMessage) -> None:
        if msg.is_command or is_command(msg.text):
            self._handle_command(msg)
            return
        speaker = resolve_speaker(self.players, msg)
        reply_to = self.repo.id_for_external(msg.reply_to_external_id)
        appended = self.repo.append_human(
            speaker, msg.text,
            external_id=msg.external_id, reply_to=reply_to,
            conversation_id=self.session.conv_id,
        )
        if appended is None:
            logger.debug("摄入去重：external_id=%s 已存在，跳过", msg.external_id)
            return
        logger.info("摄入 [%s] %s", speaker, msg.text)
        log_event("ingest", speaker=speaker, msg_id=appended.id, reply_to=reply_to)
        self._triage_user_input(msg, speaker, appended.id)

    def _handle_command(self, msg: InboundMessage) -> None:
        cmd = command_word(msg.text)
        if cmd == IAM:
            claim_name(self.players, msg)          # 认领世界名，需 sender_id
        elif cmd == PAUSE:
            self.switch.pause()
            logger.info("开关：已暂停自动 chatter")
        elif cmd == RESUME:
            self.switch.resume()
            logger.info("开关：已恢复自动 chatter")
        elif cmd == STATUS:
            logger.info("开关状态：%s", "暂停" if self.switch.paused else "运行")
        elif cmd == STOP:
            logger.info("收到 /stop，准备停机")
            self.request_stop()

    def _triage_user_input(self, msg: InboundMessage, speaker: str, msg_id: int) -> None:
        """usher 台口分流：escalate → 抢占当前 beat + user_forced，让 speak 循环立刻收束当前会话。

        "附和 vs 关键打断"（message-ordering §7 的判断器）就是 usher 的 absorb / escalate 在
        "要不要抢占"维度上的投影：absorb 不抢占，当前 beat 演完、下拍自然看到；escalate 抢占。
        误判只赔延迟不赔丢失——absorb 的输入已进历史，下个边界 storyteller 一定看到。
        speaker 是解析后的世界名（usher 也据世界身份判断，而非原始显示名）。
        canon 违规（decision.violation）额外把 msg_id 入队待清洗：世界回应后再抹去它，
        斩断"absorb 的破坏被后续 beat 放大成既成事实"的污染复利（M2.md §9）。
        """
        if self.usher is None:
            return
        decision = self.usher.classify(self.room, msg.text, speaker=speaker)
        if decision.escalate:
            self.interrupt(reason=f"usher:{decision.direction}")
            self.session.force_end(
                ConversationEnd(reason=USER_FORCED, summary_hook=msg.text, direction=decision.direction),
                redact_id=msg_id if decision.violation else None,
            )
            log_event(
                "usher_escalate", speaker=speaker,
                direction=decision.direction, violation=decision.violation,
            )
        else:
            log_event("usher_absorb", speaker=speaker)

    # ---- 发言（会话循环）----------------------------------------------
    async def _speak_loop(self, max_turns: int | None) -> int:
        turns = 0
        self.session.begin()                         # 播种第一段会话
        while self._running:
            if max_turns is not None and turns >= max_turns:
                break
            if self.switch.paused:
                await self._sleep(self.idle_poll_s)
                continue

            # 用户强制收束优先：提前触发一次正常的边界交接（机制与自然结束统一）
            if self.session.consume_forced_end() is not None:
                continue

            speaker_id = self.conductor.next_speaker(self.room, self.agents)
            spoke = speaker_id is not None and speaker_id in self._agent_by_id
            if spoke:
                agent = self._agent_by_id[speaker_id]
                log_event("schedule", agent=agent.name, model=agent.model_id)
                try:
                    completed = await self._speak(agent, self.session.hook)
                except Exception as exc:
                    # 单个 provider 抽风（鉴权失败/超时/限流）不应拖垮整屋子。
                    logger.exception("角色 %s 发言失败，跳过本回合", agent.name)
                    log_event("error", agent=agent.name, error=str(exc))
                else:
                    if completed:                # 被抢占的半截回合不算"世界已回应"
                        self.session.after_world_responded()
                turns += 1

            end = self.session.observe_beat(spoke)

            if spoke:
                self._maybe_compact()
                await self._sleep(self.turn_interval_s)
            elif end is None:
                # 这一拍留白且未到 lull：等人插话，别空转
                await self._sleep(self.idle_poll_s)
        return turns

    async def _speak(self, agent: Agent, conductor_instruction: str = "") -> bool:
        """生成并演出一个回合。返回 True = 整个回合演完；False = 被抢占（生成期间或演出期间）。"""
        conv_id = self.session.ensure_row()
        beat = self.delivery.beat                 # 本回合的 beat 戳：期间被抢占则产物作废
        # 1) 组装（循环线程内，只读 room；resolve 供超窗回复内联重注入）
        system, messages = prepare_turn(
            self.world, self.room, agent, conductor_instruction, resolve=self.repo.find
        )
        # 2) 网络调用下放线程池（不碰 room，无竞争）
        resp = await asyncio.to_thread(
            self.gateway.complete, system, messages, agent.model_id, self.max_tokens
        )
        # 3) 解析 + 节奏（循环线程内）；生成期间被抢占 → 整批作废（MVP：跑完再扔，不做取消）
        turn = finish_turn(agent, resp)
        if not self.delivery.push(agent, turn.bubbles, turn.pauses, beat=beat):
            return False

        # 4) 逐条演出；每条发出后立即入史（历史/持久化存完整 display，含动作括号）
        def _on_sent(pb: ParsedBubble, ext: str | None) -> None:
            self.repo.append_bubble(
                agent.name, pb.parts, pb.display,
                external_id=ext, reply_to=pb.reply_to, conversation_id=conv_id,
            )

        sent = await perform_queue(
            self.transport, self.delivery, self.room, sleep=self._sleep, on_sent=_on_sent
        )
        completed = sent == len(turn.bubbles)

        # 5) 合并记忆增量（尾部私有快照，不缓存）。半截回合也合并：说出口的部分是真发生过的。
        if turn.memory_delta and sent:
            merged = merge_memory(self.room.memory.get(agent.id, ""), turn.memory_delta)
            self.repo.save_memory(agent.id, merged)
        return completed

    def _maybe_compact(self) -> None:
        if self.compaction_model_id is None:
            return
        result = maybe_compact(
            self.gateway, self.world, self.room, self.compaction_model_id,
            max_history=self.max_history, keep_last=self.keep_last, max_tokens=self.max_tokens,
        )
        if result.compacted:
            log_event("compaction", dropped=result.dropped)
            self.repo.persist_compaction(self.keep_last)
