"""单角色单调用输出解析：多气泡切分（含显式停顿）+ 动作/语言分离 + 尾附记忆增量 JSON。

输出契约（在尾部指令中告知模型）：
- 1~3 条聊天气泡，相邻两条之间用 `{{SEPARATOR}}` 分隔；
  可写 `{{SEPARATOR:2}}` 显式指定停顿秒数，省略则由系统按长度推断；
- 动作可用 `{{ACTION}}…{{/ACTION}}` 或 `*…*` 包裹，其余为语言（引擎归一成 parts）；
- 可选：全部气泡之后用 `{{MEMORY}}` 再跟一段 JSON，作为记忆增量。

标记词表集中在 domain.markers；匹配对大小写与内部空白容忍
（`{{separator}}`、`{{ MEMORY }}`、`{{SEPARATOR : 2}}` 等变体均可识别）。

parse_turn_output 返回 (bubbles, memory_delta)：
- bubbles:      list[ParsedBubble]，每条含 parts（动作/语言）、pause_hint、reply_to；
                pause_hint 是「该气泡之前」模型显式给的停顿秒数（首条恒 None），
                实际等待由 pacing.resolve_pauses 结合角色 PacingConfig 计算。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from ..domain.markers import BUBBLE_SEPARATOR, MEMORY_MARKER
from ..domain.types import ContentPart, render_parts

logger = logging.getLogger(__name__)

MAX_BUBBLES = 3


@dataclass
class ParsedBubble:
    """一条解析后的气泡草稿（尚未分配 id；id 由 RoomState/store 铸造）。"""

    parts: list[ContentPart] = field(default_factory=list)
    pause_hint: float | None = None
    reply_to: int | None = None      # Phase C：{{REPLY:id}} 填充

    @property
    def text(self) -> str:
        """仅语言段拼接（供 pacing 之外的用途 / 断言）。"""
        return "".join(p.text for p in self.parts if p.kind == "speech")

    @property
    def display(self) -> str:
        """往外发 / 入历史的文本：动作 + 语言按序渲染。"""
        return render_parts(self.parts)

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


# 模型模仿历史里 `[发言者] 内容` 的格式，给自己台词加的前缀。只剥它**自己**的名字，
# 形如 `[小诗]`/`[小诗]：`/`小诗：`；不碰 `[叹气]` 这类舞台提示（名字不匹配就不动）。
_SELF_TAG_TEMPLATES = (
    r"^\s*\[\s*{n}\s*\]\s*[:：]?\s*",
    r"^\s*{n}\s*[:：]\s*",
)


def _strip_self_tag(bubble: str, name: str) -> str:
    for tmpl in _SELF_TAG_TEMPLATES:
        new = re.sub(tmpl.format(n=re.escape(name)), "", bubble, count=1)
        if new != bubble:
            return new.lstrip()
    return bubble


# 动作跨度：`{{ACTION}}…{{/ACTION}}`（容忍大小写/空白）或 RP 惯用的单星号 `*…*`。
# 其余为语言。两者都容忍，内部统一归到 ContentPart。
_ACTION_RE = re.compile(
    r"\{\{\s*ACTION\s*\}\}(.*?)\{\{\s*/\s*ACTION\s*\}\}"   # {{ACTION}}…{{/ACTION}}
    r"|\*([^*\n]+?)\*",                                     # *…*（单星号、不跨行）
    re.IGNORECASE | re.DOTALL,
)


def _extract_parts(text: str) -> list[ContentPart]:
    """把一条气泡文本切成有序的 动作/语言 段。无动作标记则整段为一个 speech。"""
    parts: list[ContentPart] = []
    pos = 0
    for m in _ACTION_RE.finditer(text):
        if m.start() > pos:
            seg = text[pos:m.start()].strip()
            if seg:
                parts.append(ContentPart(kind="speech", text=seg))
        action = (m.group(1) if m.group(1) is not None else m.group(2)) or ""
        action = action.strip()
        if action:
            parts.append(ContentPart(kind="action", text=action))
        pos = m.end()
    tail = text[pos:].strip()
    if tail:
        parts.append(ContentPart(kind="speech", text=tail))
    if not parts:
        parts = [ContentPart(kind="speech", text=text.strip())]
    return parts


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


def parse_turn_output(
    text: str, speaker: str | None = None
) -> tuple[list[ParsedBubble], dict | None]:
    """把一次调用的原始输出解析成 (bubbles: list[ParsedBubble], memory_delta)。

    步骤：切记忆增量 → 切气泡（含显式停顿）→ 每气泡内剥自名前缀（speaker 非空时）→
    抽动作/语言归一成 parts。剥空的气泡丢弃；首条幸存气泡无前置停顿。
    """
    body, memory_delta = _extract_memory(text)
    raw_bubbles, hints = _split_bubbles(body)

    bubbles: list[ParsedBubble] = []
    for raw, hint in zip(raw_bubbles, hints):
        b = _strip_self_tag(raw, speaker).strip() if speaker else raw
        if not b:
            continue
        parts = _extract_parts(b)
        if not any(p.text.strip() for p in parts):
            continue  # 剥完只剩空 → 丢弃
        bubbles.append(ParsedBubble(parts=parts, pause_hint=hint))
    if bubbles:
        bubbles[0].pause_hint = None  # 首条幸存气泡无前置停顿
    return bubbles, memory_delta
