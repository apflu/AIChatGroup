"""transport 无关的装配：预设 + Settings + 任一 Transport → Orchestrator。

Telegram / Foundry / headless 的入口都复用这一份 wiring（各自只负责造 transport），
避免 run_telegram / serve / try_storyteller 三处 wiring 漂移。
"""
from __future__ import annotations

import asyncio
import logging

from ..config import Settings
from ..io.gateway import ModelGateway, build_gateway
from ..io.persistence import Store
from ..io.transport.base import Transport
from ..message.conductor import ModelConductor
from ..message.conductor.base import Conductor
from ..message.usher import Usher
from ..presets import RoomPreset
from ..story.storyteller import ModelStoryteller, Storyteller
from .log_relay import EventLogRelay
from .orchestrator import Orchestrator
from .players import PlayerRegistry

logger = logging.getLogger(__name__)


def build_orchestrator(
    preset: RoomPreset,
    settings: Settings,
    transport: Transport,
    *,
    store: Store | None = None,
    gateway: ModelGateway | None = None,
    conductor: Conductor | None = None,
    storyteller: Storyteller | None = None,
) -> Orchestrator:
    """按预设装配一个 Orchestrator。store=None 则纯内存（headless/试跑）。

    缺 provider 抛 RuntimeError。conductor / storyteller 可替换（如试跑时用 RoundRobin）。
    """
    # 按可用 key + 预设内嵌 provider 装配，按 别名::模型 路由（无可用 provider 会抛 RuntimeError）
    gateway = gateway or build_gateway(settings, extra_providers=preset.providers)
    conductor = conductor or ModelConductor(gateway, settings.conductor_model)
    storyteller = storyteller or ModelStoryteller(gateway, settings.storyteller_model)
    usher = Usher(gateway, settings.usher_model)

    room_id = None
    if store is not None:
        room_id = store.ensure_room(preset.room_key)
        # 把预设种子写进摘要（仅当库里还没有）
        if store.load_summary(room_id) == ("", "") and (preset.seed_summary or preset.seed_relations):
            store.save_summary(room_id, preset.seed_summary, preset.seed_relations)

    # 玩家身份注册表（按本世界 room_id 分区）+ 预设预登记
    players = PlayerRegistry(store, room_id, agent_names={a.name for a in preset.agents})
    players.seed((p.channel, p.external_id, p.name, p.persona) for p in preset.players)

    return Orchestrator(
        world=preset.world,
        agents=preset.agents,
        gateway=gateway,
        conductor=conductor,
        transport=transport,
        storyteller=storyteller,
        usher=usher,
        players=players,
        store=store,
        room_key=preset.room_key,
        max_tokens=settings.max_tokens,
        turn_interval_s=settings.turn_interval_s,
        idle_poll_s=settings.idle_poll_s,
        compaction_model_id=settings.compaction_model,
        max_history=settings.max_history,
        keep_last=settings.keep_last,
    )


async def run_orchestrator(
    orch: Orchestrator,
    *,
    turns: int | None = None,
    relay_level: str | None = None,
) -> int:
    """跑主循环；relay_level 非空时把事件流按级别经 transport.send_system 转发（开发期观测）。"""
    relay = None
    if relay_level:
        relay = EventLogRelay(orch.transport)
        await relay.attach(level=relay_level)
        logger.info("事件流转发已开：级别≥%s 的事件将播到 transport 的系统出口", relay_level)
    try:
        return await orch.run(max_turns=turns)
    finally:
        if relay is not None:
            await relay.detach()


def serve(orch: Orchestrator, store: Store | None, settings: Settings, turns: int | None = None) -> int:
    """同步入口：跑到自然结束 / Ctrl-C，最后关库。返回完成的发言回合数。"""
    async def _run() -> int:
        try:
            return await run_orchestrator(
                orch, turns=turns,
                relay_level=settings.tg_log_level if settings.tg_log_enabled else None,
            )
        finally:
            if store is not None:
                store.close()

    return asyncio.run(_run())
