"""InMemoryTransport —— 离线/测试用的 Transport 实现。

不连任何外部服务：摄入来自手动 `feed()`，发送只记录到列表，便于断言
「谁按什么顺序说了什么」。给 Orchestrator 全循环做集成测试用。
"""
from __future__ import annotations

import asyncio

from ..domain.types import Agent
from .base import InboundMessage


class InMemoryTransport:
    def __init__(self) -> None:
        self._inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        # 发送记录：(agent_id, text)，按实际发出顺序
        self.sent: list[tuple[str, str]] = []
        # typing 提示记录：agent_id
        self.typing_calls: list[str] = []
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    def feed(self, msg: InboundMessage) -> None:
        """从外部注入一条摄入消息（测试里模拟人类 PL 说话 / 发指令）。"""
        self._inbound.put_nowait(msg)

    async def next_inbound(self) -> InboundMessage:
        return await self._inbound.get()

    async def send_typing(self, agent: Agent) -> None:
        self.typing_calls.append(agent.id)

    async def send_text(self, agent: Agent, text: str) -> None:
        self.sent.append((agent.id, text))
