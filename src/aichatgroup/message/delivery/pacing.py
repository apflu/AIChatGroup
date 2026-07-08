"""气泡停顿推断（transport-agnostic）。

把「模型的显式停顿提示 + 角色 PacingConfig」解析成每条气泡发送前应等待的秒数。
引擎侧只算数值；真正的 typing 提示 + sleep 由 M1 的 Telegram 适配层消费。

这是「让推断与角色性格接驳」的落点：同一段文本，急性子（per_char_s / explicit_scale 小）
比慢性子停得短。后续其他推断行为应循同一模式，把 factor 存进角色设定。
"""
from __future__ import annotations

from ...domain.types import PacingConfig


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def infer_pause(text: str, cfg: PacingConfig) -> float:
    """缺省推断：按气泡长度估算「打字 + 发送」耗时，并夹到 [min, max]。"""
    raw = cfg.base_pause_s + cfg.per_char_s * len(text)
    return _clamp(raw, cfg.min_pause_s, cfg.max_pause_s)


def resolve_pauses(
    bubbles: list[str],
    hints: list[float | None],
    cfg: PacingConfig,
) -> list[float]:
    """返回与 bubbles 等长的实际等待秒数列表；result[0] 恒为 0.0。

    - hints[i] 非空（模型显式指定）→ 采用 hints[i] * explicit_scale，夹到 [0, max]；
    - hints[i] 为空 → 按第 i 条气泡长度推断。
    """
    pauses: list[float] = []
    for i, bubble in enumerate(bubbles):
        if i == 0:
            pauses.append(0.0)
            continue
        hint = hints[i] if i < len(hints) else None
        if hint is not None:
            pauses.append(_clamp(hint * cfg.explicit_scale, 0.0, cfg.max_pause_s))
        else:
            pauses.append(infer_pause(bubble, cfg))
    return pauses
