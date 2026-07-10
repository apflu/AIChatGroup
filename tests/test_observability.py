"""结构化事件（loguru 之上）：级别映射、字段 bind、群转发渲染。"""
import asyncio

from loguru import logger

from aichatgroup.message.conductor import RoundRobinConductor
from aichatgroup.domain import Agent, WorldBook
from aichatgroup.io.gateway import MockGateway
from aichatgroup.observability import log_event
from aichatgroup.io.persistence import Store
from aichatgroup.runtime import Orchestrator
from aichatgroup.io.transport import InMemoryTransport


class _Capture:
    """临时挂一个 loguru sink，收集记录（level 名 + extra + message）。"""

    def __init__(self, level="TRACE"):
        self.records = []
        self._level = level
        self._id = None

    def __enter__(self):
        self._id = logger.add(
            lambda m: self.records.append(m.record), level=self._level, format="{message}"
        )
        return self

    def __exit__(self, *a):
        logger.remove(self._id)

    def events(self):
        return [(r["extra"].get("event"), r["level"].name, r["message"]) for r in self.records]


async def _fast(_s):
    await asyncio.sleep(0)


def test_log_event_binds_event_and_fields_and_omits_none():
    with _Capture() as cap:
        log_event("model_call", agent="小丸子", output_tokens=10, cost=None)
    rec = cap.records[-1]
    assert rec["extra"]["event"] == "model_call"
    assert rec["extra"]["agent"] == "小丸子"
    assert rec["extra"]["output_tokens"] == 10
    assert "cost" not in rec["extra"]        # None 省略


def test_event_levels_span_the_tiers():
    with _Capture(level="FIREHOSE") as cap:
        log_event("usher_escalate", speaker="用户", direction="disrupt")  # DEBUG
        log_event("ingest", speaker="用户", msg_id=1)                     # TRACE
        log_event("model_raw", source="usher", raw="x")                   # FIREHOSE
    by_event = {e: lvl for e, lvl, _ in cap.events()}
    assert by_event["usher_escalate"] == "DEBUG"
    assert by_event["ingest"] == "TRACE"
    assert by_event["model_raw"] == "FIREHOSE"


def test_render_is_plain_key_value_no_symbols():
    with _Capture() as cap:
        log_event("conversation_seed", intent_kind="develop_plot", hook="酒馆停电", last_reason="lull")
        log_event("usher_escalate", speaker="老陈", direction="disrupt")
        log_event("schedule", agent="小丸子", model="haiku")
    msgs = [m for _, _, m in cap.events()]
    assert "conversation_seed intent_kind=develop_plot hook=酒馆停电 last_reason=lull" in msgs
    assert "usher_escalate speaker=老陈 direction=disrupt" in msgs
    assert "schedule agent=小丸子 model=haiku" in msgs
    # 无浮夸符号
    assert all(sym not in m for m in msgs for sym in ("🎬", "🎯", "🚪", "→"))


def test_string_value_with_space_is_quoted():
    with _Capture() as cap:
        log_event("conversation_seed", intent_kind="chitchat", hook="酒馆 突然 停电")
    msg = cap.events()[-1][2]
    assert 'hook="酒馆 突然 停电"' in msg


def test_model_call_event_has_no_input_tokens():
    # 策略：model_call 只留 output + cache（不记 input tokens）
    with _Capture() as cap:
        log_event("model_call", agent="小丸子", output_tokens=17, cache_read=83, cache_creation=9)
    rec = cap.records[-1]
    assert "input_tokens" not in rec["extra"]
    assert rec["level"].name == "TRACE"       # 仍在 TRACE，供诊断 cache


def test_model_raw_is_below_trace_and_tagged_by_source():
    from loguru import logger as _lg
    from aichatgroup.observability import log_model_raw
    assert _lg.level("FIREHOSE").no < _lg.level("TRACE").no
    with _Capture(level="FIREHOSE") as cap:
        log_model_raw("usher", "advance", speaker="老陈")
    rec = cap.records[-1]
    assert rec["extra"]["event"] == "model_raw"
    assert rec["extra"]["source"] == "usher"
    assert rec["extra"]["raw"] == "advance"
    assert rec["level"].name == "FIREHOSE"
    # TRACE 级 sink 收不到 FIREHOSE（保 TRACE 可读）
    with _Capture(level="TRACE") as cap2:
        log_model_raw("generator", "哟！{{SEPARATOR}}老陈来壶酒", agent="小丸子")
    assert cap2.events() == []


def test_orchestrator_emits_lifecycle_events():
    store = Store(":memory:")
    gw = MockGateway()
    gw.push_script("小丸子", ["嗨"])
    orch = Orchestrator(
        world=WorldBook(bible="酒馆。" * 3, rules="守规矩。" * 3),
        agents=[Agent(id="a1", name="小丸子", model_id="m", base_prompt="活泼。")],
        gateway=gw, conductor=RoundRobinConductor(), transport=InMemoryTransport(),
        store=store, turn_interval_s=0.0, idle_poll_s=0.0, sleep=_fast,
    )
    with _Capture() as cap:
        asyncio.run(orch.run(max_turns=1))
    kinds = {e for e, _, _ in cap.events() if e}
    assert "conversation_seed" in kinds
    assert "schedule" in kinds
    assert "model_call" in kinds
