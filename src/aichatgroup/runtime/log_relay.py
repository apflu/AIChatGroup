"""把结构化事件流按级别转发到 Telegram 群 —— 开发期的"把引擎心声播到群里"。

一个 loguru sink，只接**带 `event` 的结构化事件**（`observability.log_event` 产出的），
按级别阈值过滤（默认 DEBUG：能看到 storyteller 播种 / conductor fire / usher 升级，
但 absorb 这类 TRACE 不进群）。转发出口是 `transport.send_system`（Telegram 里走 observer bot）。

sync→async 桥：loguru 的 sink 在**记录线程**同步调用，而发消息是异步的。所以 sink 只把文本
`call_soon_threadsafe` 投进一个 asyncio 队列，一个后台任务把它排空、逐条 `send_system`。
好处：日志不阻塞事件循环；发送失败只吞掉、不再 log 成 event → **无回环**。
"""
from __future__ import annotations

import asyncio
import contextlib

from loguru import logger

from ..io.transport.base import Transport


class TelegramLogRelay:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None
        self._sink_id: int | None = None

    async def attach(self, level: str = "DEBUG") -> None:
        """在**运行中的事件循环**里挂 sink + 起排空任务。"""
        self._loop = asyncio.get_running_loop()
        self._task = asyncio.create_task(self._drain())
        self._sink_id = logger.add(
            self._sink,
            level=level,
            format="{message}",
            filter=lambda r: r["extra"].get("event") is not None,
        )

    def _sink(self, message) -> None:
        # loguru 在记录线程同步调用；线程安全地把文本塞进 asyncio 队列
        text = message.record["message"]
        loop = self._loop
        if loop is not None:
            loop.call_soon_threadsafe(self._queue.put_nowait, text)

    async def _drain(self) -> None:
        while True:
            text = await self._queue.get()
            with contextlib.suppress(Exception):  # 发送失败不回环
                await self._transport.send_system(text)

    async def detach(self) -> None:
        if self._sink_id is not None:
            logger.remove(self._sink_id)
            self._sink_id = None
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
