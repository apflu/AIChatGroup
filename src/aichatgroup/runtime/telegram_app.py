"""把一个房间预设装配成 Telegram 多 bot 群聊并运行（供脚本复用）。

组装逻辑收在包里，脚本只管解析参数 + 打印，避免 run_telegram / serve 两处 wiring 漂移。
"""
from __future__ import annotations

import asyncio
import logging

from ..config import Settings
from ..message.conductor import ModelConductor
from ..message.usher import Usher
from ..io.gateway import build_gateway
from ..io.persistence import Store
from ..presets import load_preset
from ..story.storyteller import ModelStoryteller
from ..io.transport import TelegramTransport
from .log_relay import TelegramLogRelay
from .orchestrator import Orchestrator
from .players import PlayerRegistry

logger = logging.getLogger(__name__)


def build_orchestrator(
    preset_path: str, settings: Settings | None = None
) -> tuple[Orchestrator, Store, object]:
    """从预设 + Settings 装配一个 Orchestrator。返回 (orch, store, preset)。

    缺 provider / 缺观察者 token / 缺 chat_id 时抛 RuntimeError。
    """
    settings = settings or Settings.from_env()
    preset = load_preset(preset_path)
    tg = preset.telegram
    if not tg.observer_token or not tg.chat_id:
        raise RuntimeError("预设缺少观察者 token 或 chat_id（检查 .env 与 *_env 配置）。")

    # 按可用 key + 预设内嵌 provider 装配，按 别名::模型 路由（无可用 provider 会抛 RuntimeError）
    gateway = build_gateway(settings, extra_providers=preset.providers)
    conductor = ModelConductor(gateway, settings.director_model)
    usher = Usher(gateway, settings.usher_model)
    storyteller = ModelStoryteller(gateway, settings.storyteller_model)

    store = Store(settings.sqlite_path)
    room_id = store.ensure_room(preset.room_key)
    # 把预设种子写进摘要（仅当库里还没有）
    if store.load_summary(room_id) == ("", "") and (preset.seed_summary or preset.seed_relations):
        store.save_summary(room_id, preset.seed_summary, preset.seed_relations)

    # 玩家身份注册表（按本世界 room_id 分区）+ 预设预登记
    players = PlayerRegistry(store, room_id, agent_names={a.name for a in preset.agents})
    players.seed((p.channel, p.external_id, p.name, p.persona) for p in preset.players)

    agent_tokens = {aid: at.bot_token for aid, at in tg.agents.items() if at.bot_token}
    transport = TelegramTransport(tg.observer_token, tg.chat_id, agent_tokens)

    orch = Orchestrator(
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
    return orch, store, preset


def serve(preset_path: str, turns: int | None = None, settings: Settings | None = None) -> int:
    """同步入口：装配并跑主循环，返回完成的发言回合数。"""
    settings = settings or Settings.from_env()
    orch, store, _ = build_orchestrator(preset_path, settings)

    async def _run() -> int:
        relay = None
        if settings.tg_log_enabled:
            # 开发期把事件流按级别转发到群（observer bot 代发）；需在运行中的 loop 里挂
            relay = TelegramLogRelay(orch.transport)
            await relay.attach(level=settings.tg_log_level)
            logger.info("Telegram 日志转发已开：级别≥%s 的事件将播到群里", settings.tg_log_level)
        try:
            return await orch.run(max_turns=turns)
        finally:
            if relay is not None:
                await relay.detach()
            store.close()

    return asyncio.run(_run())
