"""结构化事件日志：log_event 产出可解析 JSON；orchestrator 埋点发出关键事件。"""
import asyncio
import json
import logging

from aichatgroup.director import RoundRobinDirector
from aichatgroup.domain import Agent, WorldBook
from aichatgroup.gateway import MockGateway
from aichatgroup.observability import log_event
from aichatgroup.persistence import Store
from aichatgroup.runtime import Orchestrator
from aichatgroup.transport import InMemoryTransport


async def _fast(_s):
    await asyncio.sleep(0)


def test_log_event_emits_json_and_omits_none(caplog):
    with caplog.at_level(logging.INFO, logger="aichatgroup.events"):
        log_event("model_call", agent="小丸子", input_tokens=10, cost=None)
    payload = json.loads(caplog.records[-1].message)
    assert payload["event"] == "model_call"
    assert payload["agent"] == "小丸子"
    assert payload["input_tokens"] == 10
    assert "cost" not in payload            # None 值省略


def test_orchestrator_emits_lifecycle_events(caplog):
    store = Store(":memory:")
    gw = MockGateway()
    gw.push_script("小丸子", ["嗨"])
    orch = Orchestrator(
        world=WorldBook(bible="酒馆。" * 3, rules="守规矩。" * 3),
        agents=[Agent(id="a1", name="小丸子", model_id="m", base_prompt="活泼。")],
        gateway=gw, director=RoundRobinDirector(), transport=InMemoryTransport(),
        store=store, turn_interval_s=0.0, idle_poll_s=0.0, sleep=_fast,
    )
    with caplog.at_level(logging.INFO, logger="aichatgroup.events"):
        asyncio.run(orch.run(max_turns=1))

    events = [
        json.loads(r.message)["event"]
        for r in caplog.records if r.name == "aichatgroup.events"
    ]
    assert "schedule" in events
    assert "model_call" in events
