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

from ...domain.markers import BUBBLE_SEPARATOR, MEMORY_MARKER
from ...domain.types import ContentPart, render_parts

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
        """仅台词段拼接——这是**角色 bot 实际发到聊天流**的内容（动作已剥离）。"""
        return "".join(p.text for p in self.parts if p.kind == "speech")

    @property
    def beats(self) -> list[str]:
        """有后果的举动段——托管给旁白（bot 0）第三人称播报。神态(gesture)不在此、直接隐去。"""
        return [p.text for p in self.parts if p.kind == "beat"]

    @property
    def display(self) -> str:
        """入历史 / 持久化的完整文本：动作(神态+举动) + 台词按序渲染。
        喂给模型的上下文用这个（形态不变、保共享缓存前缀不变式）；聊天流投递另按 kind 分流。"""
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


# 模型误回显历史里的 ⟦id⟧ 句柄（那是给它看的，不该写进台词）。
# 两种情形要分开：
#  - **气泡首**的裸句柄：模型模仿历史行 `⟦id⟧ [name]` 的书式，是格式回显、非引用 → 剥掉、不当回复。
#  - **正文中**的句柄（如 `朝⟦4⟧那边`）：模型想指向某条消息，是引用意图 → 剥掉防泄漏，
#    并把首个当作回复兜底（模型没走 {{REPLY}} 时的救济）。
_HANDLE_ECHO_RE = re.compile(r"^\s*⟦\s*\d+\s*⟧\s*")     # 行首格式回显
_HANDLE_ANY_RE = re.compile(r"⟦\s*(\d+)\s*⟧")           # 任意位置（正文引用）
# 保险丝：模型若回显人类行的 `<user>` 种类 tag（正常不该，AI 行本就不带）。
# 和 ⟦id⟧ 同属"AI 绝不该产出"的内部 tag，全局剥掉防泄漏（含首部误回显 `<user> [名字] …`）。
_USER_TAG_ANY_RE = re.compile(r"<\s*user\s*>", re.IGNORECASE)
# 回复标记：气泡首 `{{REPLY:37}}` → reply_to=37（契约位置）。
_REPLY_RE = re.compile(r"^\s*\{\{\s*REPLY\s*:\s*(\d+)\s*\}\}\s*", re.IGNORECASE)
# 任意位置的 REPLY（正文里残留的属格式错乱，防泄漏剥掉）。
_REPLY_ANY_RE = re.compile(r"\{\{\s*REPLY\s*:\s*\d+\s*\}\}", re.IGNORECASE)


def _extract_reply(bubble: str) -> tuple[str, int | None]:
    m = _REPLY_RE.match(bubble)
    if m:
        return bubble[m.end():], int(m.group(1))
    return bubble, None


def _scrub_inline_markers(bubble: str) -> tuple[str, int | None]:
    """剥掉正文里残留的内部标记（⟦id⟧、非首部的 {{REPLY:id}}）防泄漏。
    返回 (clean, 首个句柄 id 或 None)——首个句柄供调用方在没有显式 {{REPLY}} 时兜底成回复目标。"""
    m = _HANDLE_ANY_RE.search(bubble)
    first = int(m.group(1)) if m else None
    cleaned = _HANDLE_ANY_RE.sub("", bubble)
    cleaned = _REPLY_ANY_RE.sub("", cleaned)  # 正文中间的 {{REPLY:id}}（契约在首部）
    cleaned = re.sub(r"  +", " ", cleaned)    # 合并剥离后残留的空隙（不碰 CJK 无空格情形）
    return cleaned, first


# 动作分两档，解析层就区分 kind、决定投递去向：
#  - **神态**（gesture）：RP 惯用单星号 `*…*`。廉价、装饰性，聊天流里**直接隐去**（读者自行体会）。
#  - **举动**（beat）：`{{ACT:掏出匕首}}`（冒号式）或旧 `{{ACTION}}…{{/ACTION}}`。有后果、别人必须知道，
#    托管给旁白（bot 0）第三人称播报。漏标成星号的举动会被当神态隐掉——失败温和（台词仍在）。
# 其余为台词(speech)。三者都容忍，内部统一归到 ContentPart。
_ACTION_RE = re.compile(
    r"\{\{\s*ACT\s*:\s*(?P<beat1>[^{}]+?)\s*\}\}"                     # {{ACT:掏出匕首}}
    r"|\{\{\s*ACTION\s*\}\}(?P<beat2>.*?)\{\{\s*/\s*ACTION\s*\}\}"    # {{ACTION}}…{{/ACTION}}（旧式）
    r"|\*(?P<gesture>[^*\n]+?)\*",                                     # *神态*（单星号、不跨行）
    re.IGNORECASE | re.DOTALL,
)


def _extract_parts(text: str) -> list[ContentPart]:
    """把一条气泡文本切成有序的 神态/举动/台词 段。无动作标记则整段为一个 speech。"""
    parts: list[ContentPart] = []
    pos = 0
    for m in _ACTION_RE.finditer(text):
        if m.start() > pos:
            seg = text[pos:m.start()].strip()
            if seg:
                parts.append(ContentPart(kind="speech", text=seg))
        if m.group("gesture") is not None:
            kind, body = "gesture", m.group("gesture")
        else:
            kind, body = "beat", (m.group("beat1") or m.group("beat2") or "")
        body = body.strip()
        if body:
            parts.append(ContentPart(kind=kind, text=body))
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
        b = _HANDLE_ECHO_RE.sub("", raw, count=1)      # 剥行首格式回显的 ⟦id⟧（非引用）
        b = _USER_TAG_ANY_RE.sub("", b)                # 全局剥误回显的 <user>
        if speaker:
            b = _strip_self_tag(b, speaker)
        b, reply_id = _extract_reply(b.strip())        # 抽显式 {{REPLY:id}}（优先）
        b, inline_reply = _scrub_inline_markers(b)     # 剥正文残留 ⟦id⟧/{{REPLY}}，首个句柄作回复兜底
        if reply_id is None:
            reply_id = inline_reply
        b = b.strip()
        if not b:
            continue
        parts = _extract_parts(b)
        if not any(p.text.strip() for p in parts):
            continue  # 剥完只剩空 → 丢弃
        bubbles.append(ParsedBubble(parts=parts, pause_hint=hint, reply_to=reply_id))
    if bubbles:
        bubbles[0].pause_hint = None  # 首条幸存气泡无前置停顿
    return bubbles, memory_delta
