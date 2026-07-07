"""运行配置与默认模型。

模型 ID 以 Anthropic 官方现役别名为准（截至 2026-07）：
- Opus 4.8 :  claude-opus-4-8
- Sonnet 5 :  claude-sonnet-5
- Haiku 4.5:  claude-haiku-4-5
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

# 各层默认模型别名（可被环境变量覆盖）
DEFAULT_MODEL_OPUS = "claude-opus-4-8"
DEFAULT_MODEL_SONNET = "claude-sonnet-5"
DEFAULT_MODEL_HAIKU = "claude-haiku-4-5"


@dataclass
class ProviderSpec:
    """一个可配置的 provider 别名 → 具体网关的定义。

    kind 决定用哪套适配器：openai（含所有兼容端点）/ anthropic / gemini。
    内置别名 anthropic/openai/gemini 由标准 key 自动装配；这里是**额外**的命名端点，
    比如多个 OpenAI 兼容服务（deepseek / groq / 本地 vLLM）各自的 base_url + key。
    """

    alias: str
    kind: str = "openai"           # openai | anthropic | gemini
    base_url: str | None = None
    api_key: str | None = None

    @classmethod
    def from_dict(cls, d: dict) -> "ProviderSpec":
        """从声明式配置构造。字段：

            alias        必填，provider 别名（用 别名#模型 引用）
            type / kind  openai | anthropic | gemini（默认 openai）
            provider_url / base_url / url   端点地址（openai 兼容端点必填）
            api_key      直接写密钥（不推荐，会进配置文件）
            api_key_env  密钥所在的环境变量名（推荐，密钥留在 .env 里）
        """
        alias = d.get("alias") or d.get("name")
        if not alias:
            raise ValueError(f"provider 定义缺少 alias：{d!r}")
        api_key = d.get("api_key")
        if not api_key and d.get("api_key_env"):
            api_key = os.environ.get(d["api_key_env"])
        return cls(
            alias=str(alias),
            kind=str(d.get("type") or d.get("kind") or "openai").lower(),
            base_url=d.get("provider_url") or d.get("base_url") or d.get("url"),
            api_key=api_key,
        )


def load_provider_specs(path: str | os.PathLike[str]) -> list[ProviderSpec]:
    """从 JSON 文件读 provider 列表。

    文件可以是 {"providers": [ {...}, {...} ]} 或直接一个 [ {...}, {...} ] 数组。
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    items = data.get("providers", []) if isinstance(data, dict) else data
    return [ProviderSpec.from_dict(x) for x in items]


def _parse_providers() -> list[ProviderSpec]:
    """从 env 读额外 provider 定义。

    AICG_PROVIDERS=deepseek,groq
    AICG_PROVIDER_DEEPSEEK_KIND=openai
    AICG_PROVIDER_DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
    AICG_PROVIDER_DEEPSEEK_API_KEY=sk-...          # 或 *_API_KEY_ENV 间接指向另一个环境变量
    """
    raw = os.environ.get("AICG_PROVIDERS", "")
    specs: list[ProviderSpec] = []
    for alias in (a.strip() for a in raw.split(",") if a.strip()):
        up = alias.upper()
        key = os.environ.get(f"AICG_PROVIDER_{up}_API_KEY")
        if not key:
            key_env = os.environ.get(f"AICG_PROVIDER_{up}_API_KEY_ENV")
            key = os.environ.get(key_env) if key_env else None
        specs.append(ProviderSpec(
            alias=alias,
            kind=os.environ.get(f"AICG_PROVIDER_{up}_KIND", "openai").lower(),
            base_url=os.environ.get(f"AICG_PROVIDER_{up}_BASE_URL"),
            api_key=key,
        ))
    return specs


def _strip_inline_comment(value: str) -> str:
    """剥掉行内注释：`#` 前有空白才算注释起点。

    值本身可能含 `#`（如 provider_alias#model），那种 `#` 前无空白，不会被误伤。
    整段带引号的值（"..." / '...'）则原样保留、不剥注释。
    """
    v = value.strip()
    if v[:1] in ("'", '"'):
        return v
    m = re.search(r"\s#", v)
    return v[: m.start()].rstrip() if m else v


def _load_dotenv(path: Path) -> None:
    """极简 .env 加载：仅在文件存在时把 KEY=VALUE 写入 os.environ（不覆盖已存在项）。"""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = _strip_inline_comment(value).strip('"').strip("'")
        os.environ.setdefault(key, value)


@dataclass
class Settings:
    anthropic_api_key: str | None = None
    model_opus: str = DEFAULT_MODEL_OPUS
    model_sonnet: str = DEFAULT_MODEL_SONNET
    model_haiku: str = DEFAULT_MODEL_HAIKU
    # 单个发言回合默认输出上限（气泡短，无需很大）
    max_tokens: int = 1024

    # ---- 多 provider（可混用；模型写成 provider_alias#model，见 gateway/router.py）----
    openai_api_key: str | None = None
    openai_base_url: str | None = None       # 内置 openai 别名指向兼容端点时设这个
    openai_prefixes: str = ""                 # 逗号分隔的额外前缀，供裸模型名的前缀推断
    gemini_api_key: str | None = None
    # 额外的命名 provider（别名可配置；用 alias#model 引用）
    providers: list = field(default_factory=list)

    # ---- M1 编排相关 ----
    # 调度与 compaction 用便宜模型（Haiku）
    director_model: str = DEFAULT_MODEL_HAIKU
    compaction_model: str = DEFAULT_MODEL_HAIKU
    # 主循环节奏（秒）
    turn_interval_s: float = 1.5   # 两个发言回合之间的间隔（也顺带遵守 Telegram 限速）
    idle_poll_s: float = 2.0       # 暂停 / 无人接话时的轮询间隔
    # compaction 阈值
    max_history: int = 60          # 历史超过这么多条触发压缩
    keep_last: int = 20            # 压缩后保留的近期条数
    # 持久化与预设
    sqlite_path: str = "aichatgroup.sqlite"
    preset_path: str | None = None

    @classmethod
    def from_env(cls, dotenv_path: str | os.PathLike[str] | None = None) -> "Settings":
        if dotenv_path is not None:
            _load_dotenv(Path(dotenv_path))
        else:
            _load_dotenv(Path.cwd() / ".env")

        def _f(name: str, default: float) -> float:
            raw = os.environ.get(name)
            return float(raw) if raw else default

        def _i(name: str, default: int) -> int:
            raw = os.environ.get(name)
            return int(raw) if raw else default

        # provider 定义：声明式 JSON 文件 + 摊平的 env 变量，二者合并（同别名后者覆盖）
        providers = _parse_providers()
        providers_file = os.environ.get("AICG_PROVIDERS_FILE")
        if providers_file is None and (Path.cwd() / "providers.json").is_file():
            providers_file = str(Path.cwd() / "providers.json")
        if providers_file and Path(providers_file).is_file():
            providers = load_provider_specs(providers_file) + providers

        return cls(
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
            openai_api_key=os.environ.get("OPENAI_API_KEY"),
            openai_base_url=os.environ.get("OPENAI_BASE_URL"),
            openai_prefixes=os.environ.get("AICG_OPENAI_PREFIXES", ""),
            gemini_api_key=os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"),
            model_opus=os.environ.get("AICG_MODEL_OPUS", DEFAULT_MODEL_OPUS),
            model_sonnet=os.environ.get("AICG_MODEL_SONNET", DEFAULT_MODEL_SONNET),
            model_haiku=os.environ.get("AICG_MODEL_HAIKU", DEFAULT_MODEL_HAIKU),
            director_model=os.environ.get("AICG_MODEL_DIRECTOR", DEFAULT_MODEL_HAIKU),
            compaction_model=os.environ.get("AICG_MODEL_COMPACTION", DEFAULT_MODEL_HAIKU),
            turn_interval_s=_f("AICG_TURN_INTERVAL_S", 1.5),
            idle_poll_s=_f("AICG_IDLE_POLL_S", 2.0),
            max_history=_i("AICG_MAX_HISTORY", 60),
            keep_last=_i("AICG_KEEP_LAST", 20),
            sqlite_path=os.environ.get("AICG_SQLITE_PATH", "aichatgroup.sqlite"),
            preset_path=os.environ.get("AICG_PRESET_PATH"),
            providers=providers,
        )
