"""Conductor（编导）调度抽象：决定下一个说话者（或判定「这一拍留白」）。

M1 里它是「轻量」的：只管**谁说话**，不管说什么、不施加剧情压力（那是 story/storyteller）。
M2 起它升级为 beat 级时钟的 owner——在一段 conversation 内排 beat、并（配合 EndDetector）
检测会话该不该结束；会话意图由 storyteller 在边界播种、经 conductor_instruction 尾部槽注入。
`next_speaker` 返回 agent.id，或 None 表示这一拍留白。

同步接口：真实实现（ModelConductor）内部可能调便宜模型，由 Orchestrator 用
to_thread 包起来，不阻塞事件循环。

命名：M2 起统一为 **Conductor**；`Director` 是保留一个迁移周期的别名（见 docs/milestone/M2.md）。
"""
from __future__ import annotations

from typing import Protocol

from ...domain.types import Agent, RoomState


class Conductor(Protocol):
    def next_speaker(self, room: RoomState, agents: list[Agent]) -> str | None:
        """返回下一个应说话的 agent.id；None 表示这一拍没人说。"""
        ...


# 迁移期别名：保住旧公共导出与外部引用，一个周期后可移除。
Director = Conductor


def last_speaker_name(room: RoomState) -> str | None:
    return room.history[-1].speaker if room.history else None


def consecutive_count(room: RoomState, speaker: str) -> int:
    """该 speaker 在历史末尾连续出现的次数（防刷屏用）。"""
    n = 0
    for msg in reversed(room.history):
        if msg.speaker == speaker:
            n += 1
        else:
            break
    return n
