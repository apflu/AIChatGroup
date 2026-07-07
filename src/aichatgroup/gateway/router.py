"""RouterGateway —— 按 `provider_alias#model` 把一次调用分发给对应 provider 的网关。

模型选择的规范形式是 **`别名#模型名`**，例如：
    anthropic#claude-opus-4-8
    openai#gpt-4o
    gemini#gemini-2.0-flash
    deepseek#deepseek-chat        # deepseek 是自定义的兼容端点别名
路由只看 `#` 前的别名，与模型名彻底解耦——同一个模型名可以挂在不同端点上，
换 provider 只改别名、不动模型名。别名到具体网关的映射是可配置的（见 factory / config）。

向后兼容：不带 `#` 的裸模型名（如 `claude-opus-4-8`）仍按前缀推断路由，老预设不破。

**懒实例化**：网关可以用 register_lazy 登记一个工厂，真正路由到它时才构造（才触发对应
SDK 的延迟导入）。于是「环境里有某家的 key、但没装它的 SDK、也从没路由到它」不会拖垮整体。

它自身实现 ModelGateway 协议，对 engine / Orchestrator 透明；delegate 时会**剥掉别名**，
只把真实模型名传给下游网关。
"""
from __future__ import annotations

import logging
from typing import Callable

from ..domain.types import GatewayResponse
from .base import ModelGateway

logger = logging.getLogger(__name__)

# 裸模型名（无别名）时的前缀推断，向后兼容
ANTHROPIC_PREFIXES = ("claude-", "anthropic/")
OPENAI_PREFIXES = ("gpt-", "o1", "o3", "o4", "chatgpt", "openai/")
GEMINI_PREFIXES = ("gemini-", "models/gemini", "google/")


def parse_model_spec(spec: str) -> tuple[str | None, str]:
    """`别名#模型` → (别名, 模型)；无 `#` 时别名为 None，返回裸模型名。"""
    alias, sep, model = spec.partition("#")
    if sep:
        return (alias.strip().lower() or None), model.strip()
    return None, spec.strip()


class _Slot:
    """持有一个网关实例，或一个「用到才构造」的工厂。"""

    def __init__(self, instance: ModelGateway | None = None,
                 factory: Callable[[], ModelGateway] | None = None) -> None:
        self._instance = instance
        self._factory = factory

    def get(self) -> ModelGateway:
        if self._instance is None:
            assert self._factory is not None
            self._instance = self._factory()  # 首次用到才构造 → 才触发 SDK 导入
        return self._instance


class RouterGateway:
    def __init__(self) -> None:
        self._by_alias: dict[str, _Slot] = {}
        self._prefix_routes: list[tuple[tuple[str, ...], _Slot]] = []
        self._default: _Slot | None = None

    # -- 注册 -----------------------------------------------------------
    def _add(self, alias: str, slot: _Slot, prefixes: tuple[str, ...], default: bool) -> None:
        self._by_alias[alias.lower()] = slot
        if prefixes:
            self._prefix_routes.append((tuple(p.lower() for p in prefixes), slot))
        if default or self._default is None:
            self._default = slot

    def register(
        self, alias: str, gateway: ModelGateway,
        prefixes: tuple[str, ...] = (), *, default: bool = False,
    ) -> "RouterGateway":
        """注册一个已构造好的网关实例。"""
        self._add(alias, _Slot(instance=gateway), prefixes, default)
        return self

    def register_lazy(
        self, alias: str, factory: Callable[[], ModelGateway],
        prefixes: tuple[str, ...] = (), *, default: bool = False,
    ) -> "RouterGateway":
        """注册一个工厂，路由到该别名/前缀时才构造网关。"""
        self._add(alias, _Slot(factory=factory), prefixes, default)
        return self

    @property
    def aliases(self) -> list[str]:
        return sorted(self._by_alias)

    @property
    def has_provider(self) -> bool:
        return self._default is not None

    # -- 分发 -----------------------------------------------------------
    def _resolve(self, alias: str | None, model: str) -> ModelGateway:
        if alias is not None:
            slot = self._by_alias.get(alias)
            if slot is None:
                raise KeyError(f"未注册的 provider 别名 {alias!r}；已注册：{self.aliases}")
            return slot.get()
        ml = model.lower()
        for prefixes, slot in self._prefix_routes:
            if any(ml.startswith(p) for p in prefixes):
                return slot.get()
        if self._default is not None:
            logger.debug("模型 %s 未匹配别名/前缀，落到 default 网关", model)
            return self._default.get()
        raise KeyError(f"无法为模型 {model!r} 选择网关，且未设置 default")

    def route(self, spec: str) -> ModelGateway:
        return self._resolve(*parse_model_spec(spec))

    def complete(
        self, system: list[dict], messages: list[dict],
        model_id: str, max_tokens: int = 1024,
    ) -> GatewayResponse:
        alias, model = parse_model_spec(model_id)
        # 注意：下游只收真实模型名，别名已剥掉
        return self._resolve(alias, model).complete(system, messages, model, max_tokens)
