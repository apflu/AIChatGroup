"""TelegramLogRelay：按级别 + event 过滤，把事件流转发到 transport.send_system。"""
import asyncio

from loguru import logger

from aichatgroup.io.transport import InMemoryTransport
from aichatgroup.observability import log_event
from aichatgroup.runtime.log_relay import TelegramLogRelay


async def _wait_for(cond, tries=50):
    for _ in range(tries):
        if cond():
            return
        await asyncio.sleep(0)


def test_send_system_records_on_memory_transport():
    t = InMemoryTransport()
    asyncio.run(t.send_system("你好，世界"))
    assert t.system_sent == ["你好，世界"]


def test_relay_forwards_debug_events_not_trace_not_plain_logs():
    async def _run():
        t = InMemoryTransport()
        relay = TelegramLogRelay(t)
        await relay.attach(level="DEBUG")
        try:
            log_event("usher_escalate", speaker="用户", direction="disrupt")  # DEBUG → 转发
            log_event("ingest", speaker="用户", msg_id=1)                     # TRACE → 不转发
            logger.info("这是一条普通模块日志，没有 event")                    # 无 event → 不转发
            await _wait_for(lambda: len(t.system_sent) >= 1)
            # 再多让几拍，确认 absorb / 普通日志没有偷偷进来
            for _ in range(5):
                await asyncio.sleep(0)
            return list(t.system_sent)
        finally:
            await relay.detach()

    sent = asyncio.run(_run())
    assert len(sent) == 1
    assert sent[0] == "usher_escalate speaker=用户 direction=disrupt"


def test_relay_detach_removes_sink():
    async def _run():
        t = InMemoryTransport()
        relay = TelegramLogRelay(t)
        await relay.attach(level="DEBUG")
        await relay.detach()
        # detach 后再发事件，不应再入队/转发
        log_event("usher_escalate", speaker="用户", direction="probe")
        for _ in range(5):
            await asyncio.sleep(0)
        return list(t.system_sent)

    assert asyncio.run(_run()) == []
