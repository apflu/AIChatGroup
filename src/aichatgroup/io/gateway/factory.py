"""按可用 key + 额外 provider 定义，装配一个 RouterGateway。

内置别名（配了对应标准 key 才登记）：
- anthropic ← ANTHROPIC_API_KEY   （default，本项目缓存设计特化于它）
- openai    ← OPENAI_API_KEY / OPENAI_BASE_URL
- gemini    ← GEMINI_API_KEY / GOOGLE_API_KEY
额外命名别名来自 settings.providers（AICG_PROVIDERS / providers.json，见 config），用 `别名::模型` 引用。

**懒实例化**：这里只登记「用到才构造」的工厂，所以某家的 key 在环境里、但没装它的 SDK、
又从没路由到它时，不会在装配阶段就崩——只有真正拿它发消息时才会因缺包报错。

用法：
    from aichatgroup.config import Settings
    from aichatgroup.io.gateway import build_gateway
    gateway = build_gateway(Settings.from_env())   # 模型形如 anthropic::claude-opus-4-8
"""
from __future__ import annotations

from .anthropic_gateway import AnthropicGateway
from .gemini_gateway import GeminiGateway
from .openai_gateway import OpenAIGateway
from .router import (
    ANTHROPIC_PREFIXES,
    GEMINI_PREFIXES,
    OPENAI_PREFIXES,
    RouterGateway,
)


def _make_gateway(kind: str, api_key: str | None, base_url: str | None):
    if kind == "anthropic":
        return AnthropicGateway(api_key=api_key)
    if kind == "gemini":
        return GeminiGateway(api_key=api_key)
    # openai 及所有兼容端点
    return OpenAIGateway(api_key=api_key, base_url=base_url)


def build_gateway(settings, extra_providers=()) -> RouterGateway:
    """从 Settings（+ 可选的额外 provider，如预设内嵌的）装出按别名路由的网关。"""
    router = RouterGateway()

    if settings.anthropic_api_key:
        key = settings.anthropic_api_key
        router.register_lazy(
            "anthropic", lambda k=key: AnthropicGateway(api_key=k),
            ANTHROPIC_PREFIXES, default=True,
        )

    if settings.openai_api_key or settings.openai_base_url:
        extra_pref = tuple(
            p.strip().lower()
            for p in (settings.openai_prefixes or "").split(",")
            if p.strip()
        )
        okey, ourl = settings.openai_api_key, settings.openai_base_url
        router.register_lazy(
            "openai", lambda k=okey, u=ourl: OpenAIGateway(api_key=k, base_url=u),
            OPENAI_PREFIXES + extra_pref,
        )

    if settings.gemini_api_key:
        gkey = settings.gemini_api_key
        router.register_lazy(
            "gemini", lambda k=gkey: GeminiGateway(api_key=k), GEMINI_PREFIXES
        )

    # 额外命名 provider（别名可配置，仅按别名寻址，不参与前缀推断）
    for spec in list(settings.providers) + list(extra_providers):
        router.register_lazy(
            spec.alias,
            lambda s=spec: _make_gateway(s.kind, s.api_key, s.base_url),
        )

    if not router.has_provider:
        raise RuntimeError(
            "没有任何 provider 可用；至少配置 ANTHROPIC_API_KEY / OPENAI_API_KEY / "
            "GEMINI_API_KEY 之一，或在 AICG_PROVIDERS / providers.json 里定义一个别名。"
        )
    return router
