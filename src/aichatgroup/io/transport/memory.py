"""InMemoryTransport —— 离线/测试用的 Transport 实现。

不连任何外部服务：摄入来自手动 `feed()`，发送只记录到列表，便于断言
「谁按什么顺序说了什么」。给 Orchestrator 全循环做集成测试用。
"""
from __future__ import annotations

import asyncio

from ...domain.types import Agent
from .base import InboundMessage


class InMemoryTransport:
    def __init__(self) -> None:
        self._inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        # 发送记录：(agent_id, text)，按实际发出顺序（保持简单形状，供既有断言）
        self.sent: list[tuple[str, str]] = []
        # 完整发送记录：含 reply 与合成 external_id（回复相关断言用）
        self.sent_records: list[dict] = []
        # typing 提示记录：agent_id
        self.typing_calls: list[str] = []
        # 系统/旁白消息记录（send_system），供断言开发日志转发
        self.system_sent: list[str] = []
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

    async def send_text(
        self, agent: Agent, text: str, reply_to_external_id: str | None = None
    ) -> str:
        ext = f"mem:{len(self.sent)}"   # 合成稳定 external_id（不依赖时钟/随机）
        self.sent.append((agent.id, text))
        self.sent_records.append({
            "agent_id": agent.id, "text": text,
            "reply_to": reply_to_external_id, "external_id": ext,
        })
        return ext

    async def send_system(self, text: str) -> None:
        self.system_sent.append(text)
