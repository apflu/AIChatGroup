"""基础 compaction —— 共享历史超阈值时，把最老一段摘要化、沉进第 1 层。

M1 极简策略：当历史条数超过 max_history，取最老的一段（除最后 keep_last 条）
交给便宜模型压成叙事摘要，合并进 room.long_term_summary，并从历史里删掉这段。
这样第 2 层（滚动缓存的近期历史）保持有界，长期记忆沉进第 1 层（周期性重写）。

只在**边界**触发（超阈值才压），保证第 0/1 层的缓存前缀不会每拍都变。
函数就地改 room；持久化（写摘要 + 裁剪历史）由调用方负责，以保持存储无关。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from ...domain.types import RoomState, WorldBook
from ...io.gateway import ModelGateway
from ...prompts import load as load_prompt, render as render_prompt

logger = logging.getLogger(__name__)

_COMPACT_SYSTEM = load_prompt("compaction.system")


@dataclass
class CompactionResult:
    compacted: bool
    dropped: int = 0
    new_summary: str = ""


def maybe_compact(
    gateway: ModelGateway,
    world: WorldBook,
    room: RoomState,
    model_id: str,
    max_history: int = 60,
    keep_last: int = 20,
    max_tokens: int = 1024,
) -> CompactionResult:
    """历史超过 max_history 条则压缩最老段，返回是否压缩及删除条数。"""
    if len(room.history) <= max_history:
        return CompactionResult(compacted=False)

    old = room.history[:-keep_last] if keep_last > 0 else list(room.history)
    if not old:
        return CompactionResult(compacted=False)

    transcript = "\n".join(m.render() for m in old)
    prior = room.long_term_summary.strip() or "(暂无既有摘要)"
    user = render_prompt(
        "compaction.user", bible=world.bible.strip(), prior=prior, transcript=transcript
    )
    resp = gateway.complete(
        system=[{"type": "text", "text": _COMPACT_SYSTEM}],
        messages=[{"role": "user", "content": user}],
        model_id=model_id,
        max_tokens=max_tokens,
    )
    new_summary = resp.text.strip()

    dropped = len(old)
    room.long_term_summary = new_summary
    room.history = room.history[-keep_last:] if keep_last > 0 else []
    logger.info("compaction：摘要化并删除 %d 条旧历史，剩余 %d 条", dropped, len(room.history))
    return CompactionResult(compacted=True, dropped=dropped, new_summary=new_summary)
