# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "anthropic>=0.40",
#     "openai>=1.40",
#     "google-genai>=0.3",
#     "python-telegram-bot>=21",
# ]
# ///
"""一键跑群聊——依赖内联在脚本头（PEP 723），直接：

    uv run scripts/serve.py                       # 默认跑 examples/room.example.json
    uv run scripts/serve.py --turns 3             # 只跑 3 个发言回合后停
    uv run scripts/serve.py --preset path/to.json # 换别的房间预设

无需再手写一长串 --with；uv 会按脚本头自动装好 anthropic/openai/google-genai/
python-telegram-bot。前置准备（bot、privacy、chat_id、.env）见 scripts/run_telegram.py 顶部。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aichatgroup.config import Settings
from aichatgroup.logging_setup import setup_logging
from aichatgroup.runtime.telegram_app import serve


def main() -> int:
    parser = argparse.ArgumentParser(description="AI 群聊一键运行（依赖内联，uv run 即可）")
    parser.add_argument("--preset", default="examples/room.example.json",
                        help="房间预设 JSON（默认 examples/room.example.json）")
    parser.add_argument("--turns", type=int, default=None,
                        help="跑满多少个发言回合后停（默认无限，Ctrl-C 停）")
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass

    Settings.from_env()  # 先加载 .env，AICG_LOG_LEVEL 才读得到（否则用默认级别）
    setup_logging(os.environ.get("AICG_LOG_LEVEL", "INFO"))
    print("=" * 60)
    print(f"不夜港 · 群聊运行中（preset={args.preset}，Ctrl-C 停）")
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
