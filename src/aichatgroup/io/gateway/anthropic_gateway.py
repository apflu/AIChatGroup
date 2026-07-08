"""Anthropic 网关实现：真实调用 Messages API，透出缓存计量字段。

模块名带 `_gateway` 后缀，避免与被延迟导入的 `anthropic` SDK 混淆。
"""
from __future__ import annotations

from ...domain.types import GatewayResponse, Usage


class AnthropicGateway:
    """真实 Anthropic 网关。anthropic SDK 延迟导入，未装包也不影响其余模块。"""

    def __init__(self, api_key: str | None = None) -> None:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - 依赖缺失路径
            raise RuntimeError(
                "未安装 anthropic 包；请安装（本项目用 uv）或改用 MockGateway。"
            ) from exc
        self._client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

    def complete(
        self,
        system: list[dict],
        messages: list[dict],
        model_id: str,
        max_tokens: int = 1024,
    ) -> GatewayResponse:
        resp = self._client.messages.create(
            model=model_id,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        u = resp.usage
        usage = Usage(
            input_tokens=getattr(u, "input_tokens", 0) or 0,
            output_tokens=getattr(u, "output_tokens", 0) or 0,
            cache_read_input_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            cache_creation_input_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
        )
        return GatewayResponse(text=text, usage=usage)
