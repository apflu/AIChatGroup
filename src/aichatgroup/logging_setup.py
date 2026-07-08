"""统一日志初始化 —— loguru 为骨架。

为什么用 loguru：
- 原生 **TRACE** 级（stdlib 没有）——usher `absorb` 这类高噪声事件正好落 TRACE、`escalate` 落 DEBUG。
- 自定义 sink 只是一个可调用对象 → 把「按级别转发到 Telegram 群」做成一个 sink 极其自然
  （见 `runtime/log_relay.py`）。

兼容既有代码：模块里散落的 `logging.getLogger(__name__).info(...)` 照旧写——`InterceptHandler`
把 stdlib logging 记录转投进 loguru，无需逐个改。结构化事件走 `observability.log_event`（也在 loguru 上）。
"""
from __future__ import annotations

import logging
import sys

from loguru import logger

_CONFIGURED = False

_CONSOLE_FORMAT = (
    "<green>{time:HH:mm:ss}</green> <level>{level: <7}</level> "
    "<cyan>{name}</cyan> | <level>{message}</level>"
)


class _InterceptHandler(logging.Handler):
    """把 stdlib logging 的记录转发给 loguru，保住既有 `getLogger().info()` 调用。"""

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - 直通
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        # 回溯到真正的调用点，让 loguru 显示正确的模块名/行号（loguru 官方 recipe）
        frame, depth = logging.currentframe(), 0
        while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def setup_logging(level: str | int = "INFO") -> None:
    """配置 loguru 控制台 sink + 接管 stdlib logging。幂等。

    level 是**控制台**级别（Telegram 转发级别在 log_relay 单独设）。
    """
    global _CONFIGURED
    if _CONFIGURED:
        return
    logger.remove()  # 清掉 loguru 默认 handler
    logger.add(sys.stderr, level=level, format=_CONSOLE_FORMAT, enqueue=False)
    # stdlib → loguru：根 logger 挂拦截器，level=0 放行全部交给 loguru 决定
    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)
    _CONFIGURED = True
