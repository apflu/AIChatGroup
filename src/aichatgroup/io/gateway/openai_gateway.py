"""OpenAI 及兼容格式网关（一套适配器覆盖多家）。

一个类靠 base_url 参数同时覆盖：OpenAI 官方、以及所有「OpenAI 兼容」端点
（DeepSeek / Together / Groq / OpenRouter / 本地 vLLM / Ollama 的 /v1 等）——
它们都走 `chat.completions` 协议，只是 base_url 与 model 名不同。

缓存：OpenAI 系是**自动前缀缓存**，无显式断点；我们把翻译后命中的 cached_tokens
读进 Usage.cache_read_input_tokens，cache_creation 记 0（这一路不区分写入）。

依赖 openai SDK，延迟导入；测试可注入 client 绕过真实网络。
"""
from __future__ import annotations

from ...domain.types import GatewayResponse, Usage
from ._translate import attr, flatten_messages, flatten_system


class OpenAIGateway:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        *,
        client=None,
    ) -> None:
        if client is not None:
            self._client = client
            return
        try:
            import openai
        except ImportError as exc:  # pragma: no cover - 依赖缺失路径
            raise RuntimeError(
                "未安装 openai 包；OpenAI/兼容端点需要它（本项目用 uv）。"
            ) from exc
        kwargs = {}
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        self._client = openai.OpenAI(**kwargs)

    def complete(
        self,
        system: list[dict],
        messages: list[dict],
        model_id: str,
        max_tokens: int = 1024,
    ) -> GatewayResponse:
        oai_messages: list[dict] = []
        system_text = flatten_system(system)
        if system_text:
            oai_messages.append({"role": "system", "content": system_text})
        oai_messages.extend(flatten_messages(messages))

        resp = self._client.chat.completions.create(
            model=model_id,
            max_tokens=max_tokens,
            messages=oai_messages,
        )
        text = resp.choices[0].message.content or ""

        u = getattr(resp, "usage", None)
        cached = attr(attr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0
        usage = Usage(
            input_tokens=attr(u, "prompt_tokens", 0) or 0,
            output_tokens=attr(u, "completion_tokens", 0) or 0,
            cache_read_input_tokens=cached,
            cache_creation_input_tokens=0,
        )
        return GatewayResponse(text=text, usage=usage)
