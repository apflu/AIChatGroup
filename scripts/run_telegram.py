"""M1 落地入口：把一个房间预设跑成 Telegram 上的多 bot 热闹群聊。

准备（一次性）：
  1. 用 BotFather 建 1 个观察者 bot + 每个角色各 1 个 bot，拿到各自 token。
  2. 对观察者 bot：/setprivacy → Disable（关掉隐私模式），否则收不到群里普通消息。
  3. 把所有 bot 拉进同一个群；拿到群的 chat_id（可用观察者 bot 打印 update 得到）。
  4. 在 .env 里填好各 token 与 chat_id（见 .env.example），并写好房间预设 JSON。

运行（依赖需自备，或直接用免 --with 的 scripts/serve.py）：
  uv run --with anthropic --with openai --with google-genai --with python-telegram-bot \
    python scripts/run_telegram.py --preset examples/room.example.json

群里 `/pause` 暂停自动 chatter、`/resume` 恢复、`/stop` 停机；人类照常插话即被摄入。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aichatgroup.logging_setup import setup_logging
from aichatgroup.runtime.telegram_app import serve


def main() -> int:
    parser = argparse.ArgumentParser(description="AI 群聊 M1 · Telegram 多 bot 运行")
    parser.add_argument("--preset", default="examples/room.example.json",
                        help="房间预设 JSON 路径（默认 examples/room.example.json）")
    parser.add_argument("--turns", type=int, default=None,
                        help="跑满多少个发言回合后停（默认无限，Ctrl-C 停）")
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass

    setup_logging(os.environ.get("AICG_LOG_LEVEL", "INFO"))
    print("=" * 60)
    print(f"不夜港 · Telegram 群聊运行中（preset={args.preset}，Ctrl-C 停）")
    print("=" * 60)
    try:
        turns = serve(args.preset, turns=args.turns)
        print(f"结束，共 {turns} 个发言回合。")
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\n收到中断，停机。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
