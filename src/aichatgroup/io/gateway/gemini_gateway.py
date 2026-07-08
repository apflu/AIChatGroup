"""Google Gemini 网关。

Gemini 的输入形状与 Anthropic/OpenAI 都不同：system 走独立的 system_instruction，
对话走 contents（role 为 user/model）。共享全知布局下我们全是 user，故把所有消息文本
拼成单条 user content 传入，最稳。

缓存：Gemini 有显式 context caching（另一套 API），此处先不接；命中的
cached_content_token_count 读进 Usage.cache_read_input_tokens 以便观测。

依赖新版统一 SDK `google-genai`（`from google import genai`），延迟导入；
测试可注入 client 绕过真实网络。
"""
from __future__ import annotations

from ...domain.types import GatewayResponse, Usage
from ._translate import attr, flatten_system, join_user_text


class GeminiGateway:
    def __init__(self, api_key: str | None = None, *, client=None) -> None:
        if client is not None:
            self._client = client
            return
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover - 依赖缺失路径
            raise RuntimeError(
                "未安装 google-genai 包；Gemini 需要它（本项目用 uv）。"
            ) from exc
        self._client = genai.Client(api_key=api_key) if api_key else genai.Client()

    def complete(
        self,
        system: list[dict],
        messages: list[dict],
        model_id: str,
        max_tokens: int = 1024,
    ) -> GatewayResponse:
        system_text = flatten_system(system)
        contents = join_user_text(messages)

        # config 用 dict 传，避免依赖 SDK 的 types 类；SDK 接受 dict 形式。
        config: dict = {"max_output_tokens": max_tokens}
        if system_text:
            config["system_instruction"] = system_text

        resp = self._client.models.generate_content(
            model=model_id,
            contents=contents,
            config=config,
        )
        text = getattr(resp, "text", None) or _extract_text(resp)

        u = getattr(resp, "usage_metadata", None)
        usage = Usage(
            input_tokens=attr(u, "prompt_token_count", 0) or 0,
            output_tokens=attr(u, "candidates_token_count", 0) or 0,
            cache_read_input_tokens=attr(u, "cached_content_token_count", 0) or 0,
            cache_creation_input_tokens=0,
        )
        return GatewayResponse(text=text, usage=usage)


def _extract_text(resp) -> str:
    """resp.text 缺失时的兜底：从 candidates[0].content.parts 拼文本。"""
    try:
        parts = resp.candidates[0].content.parts
        return "".join(getattr(p, "text", "") or "" for p in parts)
    except Exception:
        return ""
