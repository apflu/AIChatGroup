"""打印某预设里某个角色**此刻**会收到的完整 prompt（按层、标缓存断点），手动调 prompts/*.md 时用。

用法：
  uv run scripts/dump_prompt.py --preset preset/room.json                # 首个角色，空历史
  uv run scripts/dump_prompt.py --preset preset/room.json --agent a2     # 指定角色
  uv run scripts/dump_prompt.py --preset preset/room.json --db data.db   # 从库里灌近窗历史
  uv run scripts/dump_prompt.py --preset preset/room.json --hook "有人在门口徘徊"   # 带编导指令
  uv run scripts/dump_prompt.py --cheap                                  # 四个便宜模型的 system 指令

不发任何模型调用。
"""
from __future__ import annotations

import argparse
import sys

from aichatgroup.message.prompt import build_prompt
from aichatgroup.message.prompt.inspect import format_prompt
from aichatgroup.prompts import load as load_prompt

_CHEAP = ("usher.system", "conductor.system", "storyteller.system", "compaction.system")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preset", help="房间预设 JSON")
    ap.add_argument("--agent", help="角色 id（缺省取预设里第一个）")
    ap.add_argument("--db", help="SQLite 路径：从库里灌该房间的近窗历史/记忆/独知")
    ap.add_argument("--history", type=int, default=60, help="--db 时灌入的近窗条数")
    ap.add_argument("--hook", default="", help="模拟 storyteller 的会话意图（进尾部编导指令）")
    ap.add_argument("--cheap", action="store_true", help="改为打印四个便宜模型的 system 指令")
    args = ap.parse_args(argv)

    if args.cheap:
        for name in _CHEAP:
            print(f"{'─' * 72}\n[{name}.md]\n{'─' * 72}\n{load_prompt(name)}\n")
        return 0
    if not args.preset:
        ap.error("--preset 必填（或用 --cheap）")

    from aichatgroup.presets import load_preset

    preset = load_preset(args.preset)
    agent = next((a for a in preset.agents if a.id == args.agent), None) if args.agent else preset.agents[0]
    if agent is None:
        print(f"预设里没有 id={args.agent!r} 的角色；可选：{[a.id for a in preset.agents]}", file=sys.stderr)
        return 2

    if args.db:
        from aichatgroup.io.persistence import RoomRepository, Store

        repo = RoomRepository.open(Store(args.db), preset.room_key, history_limit=args.history)
        room, resolve = repo.room, repo.find
    else:
        from aichatgroup.domain import RoomState

        room = RoomState(long_term_summary=preset.seed_summary, objective_relations=preset.seed_relations)
        resolve = None

    system, messages = build_prompt(preset.world, room, agent, args.hook, resolve=resolve)
    print(format_prompt(system, messages), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
