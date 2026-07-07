"""Director 调度器抽象：决定下一个说话者（或判定「暂时没人说」）。

M1 的 director 是「轻量」的：只管**谁说话**，不管说什么、不施加剧情压力
（那是 M2 的 storyteller）。next_speaker 返回 agent.id，或 None 表示这一拍留白。

同步接口：真实实现（ModelDirector）内部可能调便宜模型，由 Orchestrator 用
to_thread 包起来，不阻塞事件循环。
"""
from __future__ import annotations

from typing import Protocol

from ..domain.types import Agent, RoomState


class Director(Protocol):
    def next_speaker(self, room: RoomState, agents: list[Agent]) -> str | None:
        """返回下一个应说话的 agent.id；None 表示这一拍没人说。"""
        ...


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
