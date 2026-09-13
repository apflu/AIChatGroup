"""控制指令词表 —— transport（标 is_command）与 runtime（执行）共用的一份定义。

指令**不进聊天历史**、不喂模型。除 `/iam`（认领世界名，需 sender_id）外都是开关键类的运行时控制。
"""
from __future__ import annotations

PAUSE = "/pause"
RESUME = "/resume"
STATUS = "/status"
STOP = "/stop"
IAM = "/iam"

# 开关键类控制指令（transport 据此标 is_command；orchestrator 据此分派）
CONTROL_COMMANDS: tuple[str, ...] = (PAUSE, RESUME, STATUS, STOP)
ALL_COMMANDS: tuple[str, ...] = CONTROL_COMMANDS + (IAM,)


def command_word(text: str) -> str:
    """取一条输入的首个词（小写）——是不是指令看它是否在词表里。"""
    return text.strip().split(" ", 1)[0].lower()


def is_command(text: str) -> bool:
    return command_word(text) in ALL_COMMANDS
