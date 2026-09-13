"""把组装好的 (system, messages) 渲成一份可读的文本：按层标注、标出缓存断点。

给两处用：`scripts/dump_prompt.py`（手动调 prompt 时看模型到底收到了什么）和
`tests/test_prompt_golden.py`（快照——改 prompts/*.md 后 diff 直接显示模型输入变了哪几行）。
输出是确定性的纯文本，不含时间戳、不含 usage。
"""
from __future__ import annotations

_RULE = "─" * 72


def _block_text(content: str | list[dict]) -> tuple[str, bool]:
    """content 是纯字符串或 block 列表 → (拼接文本, 是否带 cache_control)。"""
    if isinstance(content, str):
        return content, False
    texts, cached = [], False
    for b in content:
        texts.append(b.get("text", ""))
        cached = cached or "cache_control" in b
    return "\n".join(texts), cached


def format_prompt(system: list[dict], messages: list[dict]) -> str:
    """按 system 块 / 每条 message 依次输出，带序号、角色和断点标记。"""
    out: list[str] = []
    for i, block in enumerate(system):
        mark = "  ◆ cache breakpoint" if "cache_control" in block else ""
        out += [_RULE, f"[system #{i}]{mark}", _RULE, block.get("text", ""), ""]
    for i, msg in enumerate(messages):
        text, cached = _block_text(msg["content"])
        mark = "  ◆ cache breakpoint" if cached else ""
        out += [_RULE, f"[message #{i} role={msg['role']}]{mark}", _RULE, text, ""]
    return "\n".join(out).rstrip() + "\n"
