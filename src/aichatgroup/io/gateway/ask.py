"""`ask` —— "便宜模型一问一答"的统一入口。

conductor / usher / storyteller / compaction 四处都是同一形状：一段 system 散文 + 一段 user 模板
→ `gateway.complete` → 记原始输出 → 解析。把公共部分收在这里，四处只剩"算数据 + 解析"：
- system block / user message 的字典字面量只写一次；
- `log_model_raw(source, …)` 一定会被调用（不会有哪处忘了记 FIREHOSE）；
- 异常处理形态统一：`ask` 本身**不吞异常**（由调用方决定保守回落是什么），但提供
  `ask_or_none` 给"失败即回落"的场景，避免每处再抄一遍 try/except + warning。
"""
from __future__ import annotations

import logging

from ...domain.types import GatewayResponse
from ...observability import log_model_raw
from .base import ModelGateway

logger = logging.getLogger(__name__)


def ask(
    gateway: ModelGateway,
    model_id: str,
    system: str,
    user: str,
    *,
    max_tokens: int,
    source: str,
    **log_fields: object,
) -> GatewayResponse:
    """单 system 块 + 单 user 消息的一次调用；原始输出落 FIREHOSE（source 标明是谁问的）。"""
    resp = gateway.complete(
        system=[{"type": "text", "text": system}],
        messages=[{"role": "user", "content": user}],
        model_id=model_id,
        max_tokens=max_tokens,
    )
    log_model_raw(source, resp.text, **log_fields)
    return resp


def ask_or_none(
    gateway: ModelGateway,
    model_id: str,
    system: str,
    user: str,
    *,
    max_tokens: int,
    source: str,
    **log_fields: object,
) -> GatewayResponse | None:
    """同 `ask`，但网络/模型异常时记 warning 并返回 None——供"失败即保守回落"的调用方。"""
    try:
        return ask(
            gateway, model_id, system, user,
            max_tokens=max_tokens, source=source, **log_fields,
        )
    except Exception as exc:
        logger.warning("%s 模型调用失败，走保守回落：%s", source, exc)
        return None
