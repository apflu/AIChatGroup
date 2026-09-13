#!/usr/bin/env python
"""跑一轮：storyteller 决定并开一段 conversation。默认 headless；`--telegram` 走真实群。

隔离 M2 的 storyteller 路径来观察："storyteller 在会话边界（首拍）播种意图 → conductor 排 beat →
角色开聊"。用真实 gateway + ModelStoryteller。房间用预设的**种子摘要/关系**铺底，让 storyteller
首次决策有"局势"可依（否则只能看空历史瞎猜）。

两种出口：
- 默认 **headless**：InMemoryTransport，结束打印 transcript。
- `--telegram`：真实群（预设里的 observer + 角色 bot），并把事件流转发到群（observer 代发），
  于是 storyteller 的 `conversation_seed` 决定、每拍 `schedule` 都直接播在群里。需 `--with python-telegram-bot`。

日志：默认 DEBUG。想看模型原文：`export AICG_LOG_LEVEL=FIREHOSE`。

用法：
  uv run --with anthropic scripts/try_storyteller.py --turns 6
  uv run --with anthropic scripts/try_storyteller.py --round-robin          # conductor 走确定性轮流
  uv run --with anthropic --with python-telegram-bot scripts/try_storyteller.py --telegram --turns 6
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

from aichatgroup.config import Settings
from aichatgroup.io.gateway import build_gateway
from aichatgroup.io.transport import InMemoryTransport
from aichatgroup.io.transport.telegram import build_telegram_transport
from aichatgroup.logging_setup import setup_logging
from aichatgroup.message.conductor import RoundRobinConductor
from aichatgroup.presets import load_preset
from aichatgroup.runtime import build_orchestrator, run_orchestrator


def _preflight(gateway, model_id: str) -> bool:
    """探一下 storyteller 模型能否路由——ModelStoryteller 会吞异常回落闲聊，
    所以先自己打一枪，别让路由失败被静默吞掉、让整场 storyteller 变哑。"""
    try:
        gateway.complete(
            system=[{"type": "text", "text": "ping"}],
            messages=[{"role": "user", "content": "ping"}],
            model_id=model_id,
            max_tokens=4,
        )
        print(f"[preflight] storyteller 模型 {model_id} 可路由 ✓")
        return True
    except Exception as exc:
        print(f"[preflight] storyteller 模型 {model_id} 路由失败：{exc}", file=sys.stderr)
        print("  → 设 AICG_MODEL_STORYTELLER 指到你有的 provider（如 anthropic::claude-opus-5）。", file=sys.stderr)
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="试跑 storyteller 决定一段会话（headless / telegram）")
    ap.add_argument("--preset", default="examples/room.example.json")
    ap.add_argument("--turns", type=int, default=6, help="发言回合上限；<=0 表示跑到 Ctrl-C")
    ap.add_argument("--telegram", action="store_true", help="走真实 Telegram 群（否则 headless）")
    ap.add_argument("--round-robin", action="store_true",
                    help="conductor 走确定性轮流（省 conductor 模型调用，聚焦 storyteller）")
    args = ap.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass

    settings = Settings.from_env()  # 先加载 .env，AICG_LOG_LEVEL 才读得到（否则用默认级别）
    setup_logging(os.environ.get("AICG_LOG_LEVEL", "DEBUG"))
    preset = load_preset(args.preset)

    try:
        gateway = build_gateway(settings, extra_providers=preset.providers)
        transport = build_telegram_transport(preset) if args.telegram else InMemoryTransport()
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 2

    if not _preflight(gateway, settings.storyteller_model):
        return 2

    conductor = RoundRobinConductor() if args.round_robin else None
    turns_cap = None if args.turns <= 0 else args.turns

    # headless：无 store，故用预设种子摘要/关系铺底，storyteller 首次播种时才有"局势"可依
    settings.turn_interval_s = 0.0
    settings.idle_poll_s = 0.0
    orch = build_orchestrator(preset, settings, transport, gateway=gateway, conductor=conductor)
    orch.room.long_term_summary = preset.seed_summary
    orch.room.objective_relations = preset.seed_relations

    print("=" * 60)
    print(f"storyteller 试跑：preset={args.preset}  turns={turns_cap or '∞'}  "
          f"出口={'telegram' if args.telegram else 'headless'}")
    print(f"storyteller={settings.storyteller_model}  usher={settings.usher_model}  "
          f"conductor={'round-robin' if args.round_robin else settings.conductor_model}")
    print(f"局势：{preset.seed_summary or '（空）'}")
    print("=" * 60)

    try:
        # telegram 时把事件流转发到群（observer 代发）→ storyteller 决定/每拍 schedule 直接播群里
        turns = asyncio.run(run_orchestrator(
            orch, turns=turns_cap, relay_level=settings.tg_log_level if args.telegram else None,
        ))
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\n收到中断，停机。")
        return 0

    if not args.telegram:
        print("\n----- transcript -----")
        for aid, text in orch.transport.sent:
            name = next((a.name for a in preset.agents if a.id == aid), aid)
            print(f"  {name}: {text}")
    print(f"\n完成 {turns} 个发言回合（storyteller 的意图见 conversation_seed 日志行）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
