"""Model Gateway 抽象接口与公共辅助。

engine 只依赖 ModelGateway 协议；具体 provider 实现放在同包下的独立模块
（anthropic_gateway / mock），便于后续接入更多厂商。
"""
from __future__ import annotations

from typing import Protocol

from ..domain.types import GatewayResponse


class ModelGateway(Protocol):
    def complete(
        self,
        system: list[dict],
        messages: list[dict],
        model_id: str,
        max_tokens: int = 1024,
    ) -> GatewayResponse: ...


def block_text(content) -> str:
    """从 system block 或 message content 提取纯文本（content 可为 str 或 block 列表）。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict))
    return str(content)


def est_tokens(text: str) -> int:
    """粗略 token 估算（仅用于 Mock 计量，约 4 字符/token）。"""
    return max(1, len(text) // 4)
