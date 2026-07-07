"""Telegram 连通性冒烟 —— 不启动引擎，只验证收发链路是否打通。

它做四件事，逐 bot 报告成败，方便在正式 run_telegram 前排掉配置问题：
  1. 每个角色 bot：get_me 校验 token → send_chat_action(typing) → 发一条测试消息；
  2. 观察者 bot：get_me 校验，并检查 can_read_all_group_messages（privacy mode 是否已关）；
  3. 常见错误给出可读提示（token 错 / bot 不在群 / chat_id 错）；
  4. 可选 --poll：拉一次 getUpdates，把观察者当前能看到的最近消息打印出来。

用法：
  uv run --with anthropic --with python-telegram-bot \
    python scripts/tg_check.py --preset examples/room.example.json
  # 想顺便看观察者能收到什么（先在群里发句话，再跑）：加 --poll
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aichatgroup.config import Settings
from aichatgroup.presets import load_preset


async def _check_agent_bot(Bot, token: str, chat_id: int, name: str) -> bool:
    try:
        bot = Bot(token)
        me = await bot.get_me()
    except Exception as exc:
        print(f"  ✗ {name}: token 无效或无法连接 —— {exc}")
        return False
    try:
        await bot.send_chat_action(chat_id=chat_id, action="typing")
        await bot.send_message(chat_id=chat_id, text=f"[{name}] 连通性测试 ✓（@{me.username}）")
        print(f"  ✓ {name}: @{me.username} 已向 chat_id={chat_id} 发送成功")
        return True
    except Exception as exc:
        hint = "（确认这个 bot 已被拉进群、且 chat_id 正确）"
        print(f"  ✗ {name}: 发送失败 —— {exc} {hint}")
        return False


async def _check_observer(Bot, token: str, chat_id: int, poll: bool) -> bool:
    try:
        bot = Bot(token)
        me = await bot.get_me()
    except Exception as exc:
        print(f"  ✗ 观察者: token 无效或无法连接 —— {exc}")
        return False
    can_read = getattr(me, "can_read_all_group_messages", None)
    print(f"  ✓ 观察者: @{me.username}")
    if can_read is False:
        print("    ⚠ privacy mode 仍开着（can_read_all_group_messages=False）——"
              "去 BotFather /setprivacy → Disable，否则收不到群里普通消息。")
    elif can_read is True:
        print("    ✓ privacy mode 已关，可读群内全部消息。")
    else:
        print("    · 无法确定 privacy 状态（API 未返回该字段）。")

    if poll:
        try:
            updates = await bot.get_updates(timeout=1)
        except Exception as exc:
            print(f"    · getUpdates 失败：{exc}")
            return True
        seen = [u for u in updates if u.effective_message
                and u.effective_message.chat_id == chat_id]
        print(f"    · 本群最近可见消息 {len(seen)} 条：")
        for u in seen[-5:]:
            m = u.effective_message
            who = m.from_user.full_name if m.from_user else "?"
            print(f"        [{who}] {m.text}")
    return True


async def _run(preset_path: str, poll: bool, env_path: str) -> int:
    try:
        from telegram import Bot
    except ImportError:
        print("需要 python-telegram-bot：uv run --with python-telegram-bot ...", file=sys.stderr)
        return 2

    # 载入 .env 到 os.environ，供 load_preset 解析预设里的 *_env（token / chat_id）。
    Settings.from_env(env_path)

    preset = load_preset(preset_path)
    tg = preset.telegram
    if not tg.chat_id:
        print("预设/环境里缺少 chat_id。", file=sys.stderr)
        return 2
    chat_id = int(tg.chat_id)

    print("=" * 56)
    print(f"Telegram 连通性检查（room={preset.room_key}, chat_id={chat_id}）")
    print("=" * 56)

    ok = True
    print("角色 bot 发送：")
    for agent in preset.agents:
        at = tg.agents.get(agent.id)
        if not at or not at.bot_token:
            print(f"  · {agent.name}: 未配置 bot token（跳过）")
            ok = False
            continue
        ok &= await _check_agent_bot(Bot, at.bot_token, chat_id, agent.name)

    print("观察者 bot：")
    if tg.observer_token:
        ok &= await _check_observer(Bot, tg.observer_token, chat_id, poll)
    else:
        print("  · 未配置观察者 token（跳过）")
        ok = False

    print("-" * 56)
    print("结果：" + ("全部通过 ✓" if ok else "有项目未通过，见上。"))
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Telegram 收发连通性冒烟")
    parser.add_argument("--preset", default="examples/room.example.json", help="房间预设 JSON")
    parser.add_argument("--poll", action="store_true",
                        help="顺便 getUpdates 打印观察者当前能看到的最近消息")
    parser.add_argument("--env", default=".env", help="要加载的 .env 路径（默认项目根 .env）")
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass

    return asyncio.run(_run(args.preset, args.poll, args.env))


if __name__ == "__main__":
    raise SystemExit(main())
