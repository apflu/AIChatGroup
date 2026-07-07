"""运行配置与默认模型。

模型 ID 以 Anthropic 官方现役别名为准（截至 2026-07）：
- Opus 4.8 :  claude-opus-4-8
- Sonnet 5 :  claude-sonnet-5
- Haiku 4.5:  claude-haiku-4-5
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# 各层默认模型别名（可被环境变量覆盖）
DEFAULT_MODEL_OPUS = "claude-opus-4-8"
DEFAULT_MODEL_SONNET = "claude-sonnet-5"
DEFAULT_MODEL_HAIKU = "claude-haiku-4-5"


def _load_dotenv(path: Path) -> None:
    """极简 .env 加载：仅在文件存在时把 KEY=VALUE 写入 os.environ（不覆盖已存在项）。"""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


@dataclass
class Settings:
    anthropic_api_key: str | None = None
    model_opus: str = DEFAULT_MODEL_OPUS
    model_sonnet: str = DEFAULT_MODEL_SONNET
    model_haiku: str = DEFAULT_MODEL_HAIKU
    # 单个发言回合默认输出上限（气泡短，无需很大）
    max_tokens: int = 1024

    @classmethod
    def from_env(cls, dotenv_path: str | os.PathLike[str] | None = None) -> "Settings":
        if dotenv_path is not None:
            _load_dotenv(Path(dotenv_path))
        else:
            _load_dotenv(Path.cwd() / ".env")
        return cls(
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
            model_opus=os.environ.get("AICG_MODEL_OPUS", DEFAULT_MODEL_OPUS),
            model_sonnet=os.environ.get("AICG_MODEL_SONNET", DEFAULT_MODEL_SONNET),
            model_haiku=os.environ.get("AICG_MODEL_HAIKU", DEFAULT_MODEL_HAIKU),
        )
