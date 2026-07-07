"""单角色单调用输出解析：多气泡切分（含显式停顿）+ 尾附记忆增量 JSON。

输出契约（在尾部指令中告知模型）：
- 1~3 条聊天气泡，相邻两条之间用 `{{SEPARATOR}}` 分隔；
  可写 `{{SEPARATOR:2}}` 显式指定停顿秒数，省略则由系统按长度推断；
- 可选：全部气泡之后用 `{{MEMORY}}` 再跟一段 JSON，作为记忆增量。

标记词表集中在 domain.markers；匹配对大小写与内部空白容忍
（`{{separator}}`、`{{ MEMORY }}`、`{{SEPARATOR : 2}}` 等变体均可识别）。

parse_turn_output 返回 (bubbles, pause_hints, memory_delta)：
- bubbles:      list[str]
- pause_hints:  list[float|None]，与 bubbles 等长；pause_hints[i] 是「第 i 条气泡
                之前」模型显式给出的停顿秒数；pause_hints[0] 恒为 None（首条无前置停顿）。
                实际等待时间由 pacing.resolve_pauses 结合角色 PacingConfig 计算。
"""
from __future__ import annotations

import json
import logging
import re

from ..domain.markers import BUBBLE_SEPARATOR, MEMORY_MARKER

logger = logging.getLogger(__name__)

MAX_BUBBLES = 3

def _marker_inner(marker: str) -> str:
    """取标记里的词（去掉 {{ }} 与空白），如 '{{SEPARATOR}}' → 'SEPARATOR'。"""
    return marker.strip("{}").strip()


# 分隔符：捕获可选的停顿秒数分组。
_SEP_RE = re.compile(
    r"\{\{\s*"
    + re.escape(_marker_inner(BUBBLE_SEPARATOR))
    + r"\s*(?::\s*(\d+(?:\.\d+)?)\s*)?\}\}",
    re.IGNORECASE,
)


def _tolerant_marker_re(marker: str) -> re.Pattern[str]:
    return re.compile(r"\{\{\s*" + re.escape(_marker_inner(marker)) + r"\s*\}\}", re.IGNORECASE)


_MEM_RE = _tolerant_marker_re(MEMORY_MARKER)

# 尾部闭合标记：模型常把 {{MEMORY}} 当标签补一个闭合。容忍新式 {{/MEMORY}} / {{MEMORY}}，
# 也兼容旧式 </MEMORY> / <<MEMORY>>，一律从末尾剥掉。
_CLOSE_MEM_RE = re.compile(
    r"\s*(?:\{\{\s*/?\s*" + re.escape(_marker_inner(MEMORY_MARKER)) + r"\s*\}\}"
    r"|<<?\s*/?\s*" + re.escape(_marker_inner(MEMORY_MARKER)) + r"\s*>>?)\s*$",
    re.IGNORECASE,
)


def _loads_tolerant(raw: str) -> dict | None:
    """尽力把一段文本解析成 JSON 对象；失败则退一步截取首个 { 到末个 }。"""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        i, j = raw.find("{"), raw.rfind("}")
        if 0 <= i < j:
            try:
                return json.loads(raw[i : j + 1])
            except json.JSONDecodeError:
                return None
        return None


def _extract_memory(text: str) -> tuple[str, dict | None]:
    """切出记忆增量。返回 (气泡区文本, memory_delta 或 None)。"""
    m = _MEM_RE.search(text)
    if m is None:
        return text, None
    body = text[: m.start()]
    raw = _strip_code_fence(text[m.end():].strip())
    raw = _CLOSE_MEM_RE.sub("", raw).strip()  # 剥掉尾部 </MEMORY> 之类
    if not raw:
        return body, None
    delta = _loads_tolerant(raw)
    if delta is None:
        logger.warning("记忆增量 JSON 解析失败，已忽略：%r", raw[:120])
        return body, None
    if not isinstance(delta, dict):
        logger.warning("记忆增量应为对象，实际为 %s，已忽略", type(delta).__name__)
        return body, None
    return body, delta


def _strip_code_fence(raw: str) -> str:
    """容忍模型把 JSON 包在 ```json ... ``` 里。"""
    if raw.startswith("```"):
        raw = raw[3:]
        if raw[:4].lower() == "json":
            raw = raw[4:]
        if raw.endswith("```"):
            raw = raw[:-3]
    return raw.strip()


def _split_bubbles(body: str) -> tuple[list[str], list[float | None]]:
    """按分隔符切分气泡，并对齐每条气泡之前的显式停顿。"""
    # re.split 带捕获组时，分隔符捕获值会交错出现在结果里：
    #   [bubble0, cap0, bubble1, cap1, bubble2, ...]
    segs = _SEP_RE.split(body)
    bubbles_raw = segs[0::2]
    caps_raw = segs[1::2]  # len == len(bubbles_raw) - 1；caps_raw[i] 在 bubble i+1 之前

    bubbles: list[str] = []
    hints: list[float | None] = []
    for i, raw in enumerate(bubbles_raw):
        text = raw.strip()
        if not text:
            continue  # 丢弃空气泡（及其前置停顿，无意义）
        cap = caps_raw[i - 1] if i >= 1 else None
        bubbles.append(text)
        # 首条幸存气泡无前置停顿
        hints.append(None if not bubbles[:-1] else (float(cap) if cap else None))

    if len(bubbles) > MAX_BUBBLES:
        logger.info("模型输出了 %d 条气泡，截断为前 %d 条", len(bubbles), MAX_BUBBLES)
        bubbles = bubbles[:MAX_BUBBLES]
        hints = hints[:MAX_BUBBLES]
    return bubbles, hints


def parse_turn_output(text: str) -> tuple[list[str], list[float | None], dict | None]:
    """把一次调用的原始输出解析成 (bubbles, pause_hints, memory_delta)。"""
    body, memory_delta = _extract_memory(text)
    bubbles, hints = _split_bubbles(body)
    return bubbles, hints, memory_delta
