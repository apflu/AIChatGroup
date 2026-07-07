"""结构化事件日志 —— 消息/回合生命周期的机器可读事件流。

与人类可读日志分开：事件走独立 logger `aichatgroup.events`，每条是一行 JSON，便于
后续被 storyteller（读节拍/张力）、成本核算、观测面板消费。埋点在 Orchestrator 的
生命周期点：ingest / schedule / model_call / compaction / error。

刻意保持极简：不引依赖、不做聚合、不算成本（先记 tokens，定价换算是后话）。
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger("aichatgroup.events")


def log_event(kind: str, **fields) -> None:
    """发一条结构化事件（一行 JSON）。None 值省略，保持简洁。"""
    payload = {"event": kind}
    payload.update({k: v for k, v in fields.items() if v is not None})
    logger.info(json.dumps(payload, ensure_ascii=False, sort_keys=True))
