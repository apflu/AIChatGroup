"""把「Anthropic 形状」的规范 prompt 翻译成各家 provider 的输入格式。

规范线格式（PromptBuilder 产出、也是 ModelGateway 协议约定）：
- system:   list[block]，每个 block 形如 {"type":"text","text":..., "cache_control":...}
- messages: list[{"role":..., "content": str | list[block]}]

非 Anthropic 的家不认 cache_control（OpenAI 自动前缀缓存、Gemini 另有显式 context cache），
翻译时统一丢掉断点、只取纯文本。共享全知布局下我们的消息全是 user 角色（无 assistant），
所以对 OpenAI/Gemini 都能安全展开。
"""
from __future__ import annotations

from .base import block_text


def flatten_system(system: list[dict]) -> str:
    """多个 system block → 单段 system 文本。

    system 的每个元素本身就是一个 block（{"type":"text","text":...}），
    直接取其 text；不要走 block_text（那是给「消息 content」用的）。
    """
    parts = []
    for b in system:
        parts.append(b.get("text", "") if isinstance(b, dict) else str(b))
    return "\n\n".join(parts).strip()


def flatten_messages(messages: list[dict]) -> list[dict]:
    """剥掉 cache_control，content 归一成纯文本字符串。"""
    return [{"role": m["role"], "content": block_text(m["content"])} for m in messages]


def join_user_text(messages: list[dict]) -> str:
    """把全部消息文本拼成一段（Gemini 单轮 user content 用）。"""
    return "\n\n".join(block_text(m["content"]) for m in messages).strip()


def attr(obj, name: str, default=0):
    """从对象或 dict 里健壮取值（各家 usage 有的是属性、有的是 dict）。"""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)
