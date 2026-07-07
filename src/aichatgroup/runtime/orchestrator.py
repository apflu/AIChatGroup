"""Orchestrator —— transport-agnostic 的 tick 主循环。

把摄入、调度、发言、发送、持久化、开关键、compaction 串成一个异步循环。
它不认识 Telegram；只依赖 Transport / Director / Store 抽象。

并发模型（要点）：
- 两个协程共享一份 RoomState：`_ingest_loop`（摄入人类/外部消息）与
  `_speak_loop`（驱动角色说话）。二者都只在**事件循环线程**里读写 room。
- 唯一下放到线程池（to_thread）的是**网络调用** `gateway.complete`——它不碰 room，
  因此不会与摄入协程竞争。prompt 组装、解析、追加历史全部在循环线程内完成，天然安全。
- director / compaction 的模型调用为简洁起见同步执行（便宜、低频），会短暂占用循环；
  MVP 可接受，后续可同样拆成「循环内组装 + 线程内调用」。
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Awaitable, Callable

from ..director.base import Director
from ..domain.types import Agent, RoomState, WorldBook
from ..engine.compaction import maybe_compact
from ..engine.parsing import parse_turn_output
from ..engine.pacing import resolve_pauses
from ..engine.turn import merge_memory
from ..gateway import ModelGateway
from ..prompt import build_prompt
from ..persistence.store import Store
from ..transport.base import InboundMessage, Transport
from .switch import MasterSwitch

logger = logging.getLogger(__name__)

_COMMANDS = {"/pause", "/resume", "/status", "/stop"}


class Orchestrator:
    def __init__(
        self,
        world: WorldBook,
        agents: list[Agent],
        gateway: ModelGateway,
        director: Director,
        transport: Transport,
        *,
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
        self.director = director
        self.transport = transport
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

        self._running = False
        self._stop_event = asyncio.Event()

    # ---- 生命周期 ------------------------------------------------------
    async def run(self, max_turns: int | None = None) -> int:
        """启动主循环。max_turns 非空时跑满该回合数后自动停（测试/演示用）。

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

    # ---- 摄入 ----------------------------------------------------------
    async def _ingest_loop(self) -> None:
        while self._running:
            msg = await self.transport.next_inbound()
            self._handle_inbound(msg)

    def _handle_inbound(self, msg: InboundMessage) -> None:
        text = msg.text.strip()
        if msg.is_command or text.split(" ", 1)[0] in _COMMANDS:
            self._handle_command(text)
            return
        # 去重 + 追加共享历史（store id 为权威 handle）
        mid = None
        if self.store is not None and self.room_id is not None:
            mid = self.store.append_message(
                self.room_id, msg.speaker, msg.text, external_id=msg.external_id
            )
            if mid is None:
                logger.debug("摄入去重：external_id=%s 已存在，跳过", msg.external_id)
                return
        meta = {"external_id": msg.external_id} if msg.external_id else None
        self.room.append(msg.speaker, msg.text, id=mid, author_kind="human", meta=meta)
        logger.info("摄入 [%s] %s", msg.speaker, msg.text)

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

    # ---- 发言 ----------------------------------------------------------
    async def _speak_loop(self, max_turns: int | None) -> int:
        turns = 0
        while self._running:
            if max_turns is not None and turns >= max_turns:
                break
            if self.switch.paused:
                await self._sleep(self.idle_poll_s)
                continue
            speaker_id = self.director.next_speaker(self.room, self.agents)
            if speaker_id is None or speaker_id not in self._agent_by_id:
                await self._sleep(self.idle_poll_s)
                continue
            agent = self._agent_by_id[speaker_id]
            try:
                await self._speak(agent)
            except Exception:
                # 单个 provider 抽风（鉴权失败/超时/限流）不应拖垮整屋子；
                # 记下来、跳过这个角色本回合，其他角色照常热闹。
                logger.exception("角色 %s 发言失败，跳过本回合", agent.name)
            turns += 1
            await self._maybe_compact()
            await self._sleep(self.turn_interval_s)
        return turns

    async def _speak(self, agent: Agent) -> None:
        # 1) 组装 prompt（循环线程内，只读 room）
        system, messages = build_prompt(self.world, self.room, agent)
        # 2) 网络调用下放线程池（不碰 room，无竞争）
        resp = await asyncio.to_thread(
            self.gateway.complete, system, messages, agent.model_id, self.max_tokens
        )
        # 3) 解析 + 节奏（循环线程内）
        bubbles, hints, memory_delta = parse_turn_output(resp.text, speaker=agent.name)
        pauses = resolve_pauses(bubbles, hints, agent.pacing)
        logger.info(
            "回合 %s bubbles=%d cache_read=%d cache_creation=%d",
            agent.name, len(bubbles),
            resp.usage.cache_read_input_tokens, resp.usage.cache_creation_input_tokens,
        )
        # 4) 逐条发送：typing → 等 pause → 发气泡 → 入历史（模拟真人连发）
        for bubble, pause in zip(bubbles, pauses):
            await self.transport.send_typing(agent)
            if pause > 0:
                await self._sleep(pause)
            await self.transport.send_text(agent, bubble)
            # store id 为权威 handle；无 store 时 RoomState 自铸本地 id
            mid = None
            if self.store is not None and self.room_id is not None:
                mid = self.store.append_message(self.room_id, agent.name, bubble)
            self.room.append(agent.name, bubble, id=mid)
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
        if result.compacted and self.store is not None and self.room_id is not None:
            self.store.save_summary(self.room_id, self.room.long_term_summary, self.room.objective_relations)
            self.store.trim_history(self.room_id, self.keep_last)
