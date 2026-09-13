# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "aichatgroup[telegram,openai,gemini] @ file:///${PROJECT_ROOT}",
# ]
# ///
"""一键跑群聊——依赖内联在脚本头（PEP 723），直接：

    uv run scripts/serve.py                       # 默认跑 examples/room.example.json
    uv run scripts/serve.py --turns 3             # 只跑 3 个发言回合后停
    uv run scripts/serve.py --preset path/to.json # 换别的房间预设

等价于 `uv run aichatgroup-serve ...`（项目环境里已装好本包时用那个更省）。
前置准备（bot、privacy、chat_id、.env）见 scripts/run_telegram.py 顶部。
"""
from aichatgroup.runtime.telegram_app import main

if __name__ == "__main__":
    raise SystemExit(main())
