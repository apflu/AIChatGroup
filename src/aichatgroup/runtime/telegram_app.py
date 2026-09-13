"""Telegram 落地面的入口：预设 → TelegramTransport → 通用装配（runtime/app.py）→ 跑。

也是 `aichatgroup-serve` 控制台命令的 main。前置准备（BotFather 建 bot、关 privacy、拿 chat_id、
填 .env）见 README「M1 · Telegram 上线」。
"""
from __future__ import annotations

import argparse
import os
import sys

from ..config import Settings
from ..io.persistence import Store
from ..io.transport.telegram import build_telegram_transport
from ..logging_setup import setup_logging
from ..presets import RoomPreset, load_preset
from .app import build_orchestrator
from .app import serve as _serve
from .orchestrator import Orchestrator


def build_telegram_orchestrator(
    preset_path: str, settings: Settings | None = None
) -> tuple[Orchestrator, Store, RoomPreset]:
    """从预设 + Settings 装配一个跑在 Telegram 上的 Orchestrator。返回 (orch, store, preset)。

    缺 provider / 缺观察者 token / 缺 chat_id 时抛 RuntimeError。
    """
    settings = settings or Settings.from_env()
    preset = load_preset(preset_path)
    transport = build_telegram_transport(preset)
    store = Store(settings.sqlite_path)
    orch = build_orchestrator(preset, settings, transport, store=store)
    return orch, store, preset


def serve(preset_path: str, turns: int | None = None, settings: Settings | None = None) -> int:
    """同步入口：装配并跑主循环，返回完成的发言回合数。"""
    settings = settings or Settings.from_env()
    orch, store, _ = build_telegram_orchestrator(preset_path, settings)
    return _serve(orch, store, settings, turns=turns)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI 群聊 · Telegram 多 bot 运行")
    parser.add_argument("--preset", default=os.environ.get("AICG_PRESET_PATH", "examples/room.example.json"),
                        help="房间预设 JSON 路径（默认 examples/room.example.json，或 AICG_PRESET_PATH）")
    parser.add_argument("--turns", type=int, default=None,
                        help="跑满多少个发言回合后停（默认无限，Ctrl-C 停）")
    args = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass

    settings = Settings.from_env()  # 先加载 .env，AICG_LOG_LEVEL 才读得到
    setup_logging(settings.log_level)
    print("=" * 60)
    print(f"群聊运行中（preset={args.preset}，Ctrl-C 停）")
    print("=" * 60)
    try:
        turns = serve(args.preset, turns=args.turns, settings=settings)
        print(f"结束，共 {turns} 个发言回合。")
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\n收到中断，停机。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
