"""Model Gateway：provider 抽象 + 多家实现（Anthropic / OpenAI 兼容 / Gemini）+ Mock。

RouterGateway 按 model_id 前缀把调用分发给对应 provider；build_gateway 按可用 key 自动装配。
上层（engine / Orchestrator）只依赖 ModelGateway 协议，混用多家模型对它透明。
"""
from .anthropic_gateway import AnthropicGateway
from .base import ModelGateway, block_text, est_tokens
from .factory import build_gateway
from .gemini_gateway import GeminiGateway
from .mock import MockGateway
from .openai_gateway import OpenAIGateway
from .router import (
    ANTHROPIC_PREFIXES,
    GEMINI_PREFIXES,
    OPENAI_PREFIXES,
    RouterGateway,
    parse_model_spec,
)

__all__ = [
    "ModelGateway",
    "AnthropicGateway",
    "OpenAIGateway",
    "GeminiGateway",
    "MockGateway",
    "RouterGateway",
    "parse_model_spec",
    "build_gateway",
    "block_text",
    "est_tokens",
    "ANTHROPIC_PREFIXES",
    "OPENAI_PREFIXES",
    "GEMINI_PREFIXES",
]
