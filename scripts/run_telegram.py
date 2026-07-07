"""M1 落地入口：把一个房间预设跑成 Telegram 上的多 bot 热闹群聊。

准备（一次性）：
  1. 用 BotFather 建 1 个观察者 bot + 每个角色各 1 个 bot，拿到各自 token。
  2. 对观察者 bot：/setprivacy → Disable（关掉隐私模式），否则收不到群里普通消息。
  3. 把所有 bot 拉进同一个群；拿到群的 chat_id（可用观察者 bot 打印 update 得到）。
  4. 在 .env 里填好各 token 与 chat_id（见 .env.example），并写好房间预设 JSON。

运行：
  uv run --with anthropic --with python-telegram-bot \
    python scripts/run_telegram.py --preset examples/room.example.json

群里 `/pause` 暂停自动 chatter、`/resume` 恢复、`/stop` 停机；人类照常插话即被摄入。
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aichatgroup.config import Settings
from aichatgroup.director import ModelDirector
from aichatgroup.gateway import build_gateway
from aichatgroup.logging_setup import setup_logging
from aichatgroup.persistence import Store
from aichatgroup.presets import load_preset
from aichatgroup.runtime import Orchestrator
from aichatgroup.transport import TelegramTransport


def main() -> int:
    parser = argparse.ArgumentParser(description="AI 群聊 M1 · Telegram 多 bot 运行")
    parser.add_argument("--preset", required=True, help="房间预设 JSON 路径")
    parser.add_argument("--turns", type=int, default=None,
                        help="跑满多少个发言回合后停（默认无限，Ctrl-C 停）")
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass

    setup_logging()
    settings = Settings.from_env()

    preset = load_preset(args.preset)
    tg = preset.telegram
    if not tg.observer_token or not tg.chat_id:
        print("预设缺少观察者 token 或 chat_id（检查 .env 与 *_env 配置）。", file=sys.stderr)
        return 2

    try:
        # 按可用 key + 预设内嵌 provider 装配，按 别名#模型 路由
        gateway = build_gateway(settings, extra_providers=preset.providers)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 2
    director = ModelDirector(gateway, settings.director_model)
    store = Store(settings.sqlite_path)
    # 把预设种子写进摘要（仅当库里还没有）
    room_id = store.ensure_room(preset.room_key)
    existing = store.load_summary(room_id)
    if existing == ("", "") and (preset.seed_summary or preset.seed_relations):
        store.save_summary(room_id, preset.seed_summary, preset.seed_relations)

    agent_tokens = {
        aid: at.bot_token for aid, at in tg.agents.items() if at.bot_token
    }
    transport = TelegramTransport(tg.observer_token, tg.chat_id, agent_tokens)

    orch = Orchestrator(
        world=preset.world,
        agents=preset.agents,
        gateway=gateway,
        director=director,
        transport=transport,
        store=store,
        room_key=preset.room_key,
        max_tokens=settings.max_tokens,
        turn_interval_s=settings.turn_interval_s,
        idle_poll_s=settings.idle_poll_s,
        compaction_model_id=settings.compaction_model,
        max_history=settings.max_history,
        keep_last=settings.keep_last,
    )

    print("=" * 60)
    print(f"不夜港 · Telegram 群聊运行中（room={preset.room_key}，Ctrl-C 停）")
    print("=" * 60)
    try:
        turns = asyncio.run(orch.run(max_turns=args.turns))
        print(f"结束，共 {turns} 个发言回合。")
    except KeyboardInterrupt:
        print("\n收到中断，停机。")
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
