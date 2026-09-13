"""M1 落地入口：把一个房间预设跑成 Telegram 上的多 bot 热闹群聊。

等价于控制台命令 `aichatgroup-serve`（见 pyproject [project.scripts]）：

  uv run aichatgroup-serve --preset examples/room.example.json
  uv run scripts/run_telegram.py --preset examples/room.example.json   # 同上

准备（一次性）：
  1. 用 BotFather 建 1 个观察者 bot + 每个角色各 1 个 bot，拿到各自 token。
  2. 所有 bot：/setprivacy → Disable（观察者收群消息必需；角色 bot 原生 reply 人类消息必需）。
  3. 把所有 bot 拉进同一个群；拿到群的 chat_id（可用 scripts/tg_check.py --poll 得到）。
  4. 在 .env 里填好各 token 与 chat_id（见 .env.example），并写好房间预设 JSON。

群里 `/pause` 暂停自动 chatter、`/resume` 恢复、`/stop` 停机；人类照常插话即被摄入。
"""
from aichatgroup.runtime.telegram_app import main

if __name__ == "__main__":
    raise SystemExit(main())
