"""规则型 conductor —— 无需模型，确定性，供离线回放与测试使用。

RoundRobinConductor：按 agents 固定顺序轮流，跳过刚说过话的人，保证不自言自语。
它永不返回 None（总有人接话），因此适合把「热闹」跑满的冒烟/回放场景。
"""
from __future__ import annotations

from ...domain.types import Agent, RoomState
from .base import last_speaker_name


class RoundRobinConductor:
    def __init__(self) -> None:
        self._cursor = 0

    def next_speaker(self, room: RoomState, agents: list[Agent]) -> str | None:
        if not agents:
            return None
        last = last_speaker_name(room)
        n = len(agents)
        # 从游标位置起顺序找第一个「不是刚说过话的人」，保证公平轮流。
        for _ in range(n):
            cand = agents[self._cursor % n]
            self._cursor += 1
            if n == 1 or cand.name != last:
                return cand.id
        # 理论不可达（n>=1 时必有返回）；兜底
        return agents[self._cursor % n].id


# 迁移期别名：保住旧公共导出与外部引用，一个周期后可移除。
RoundRobinDirector = RoundRobinConductor
