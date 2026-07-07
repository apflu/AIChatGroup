"""开关键 —— 暂停/恢复自动 chatter。

暂停时角色不再自动接话，但人类消息仍照常摄入进共享历史（恢复后角色能看到）。
"""
from __future__ import annotations


class MasterSwitch:
    def __init__(self, paused: bool = False) -> None:
        self._paused = paused

    @property
    def paused(self) -> bool:
        return self._paused

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def toggle(self) -> bool:
        self._paused = not self._paused
        return self._paused
