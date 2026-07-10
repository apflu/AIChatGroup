"""结构化事件日志 —— 消息/会话生命周期的机器可读事件流（loguru 之上）。

`log_event(kind, **fields)` 做两件事：
1. 把 `event=kind` 与各字段 **bind 进 loguru 记录的 extra**——结构化数据留着，将来"观测面板"
   （sequence-diagram 式前端）对事件流做 fold 就吃这个。
2. 按事件类型选一个**日志级别**发一行 `kind key=value ...`（英文键、内容原样、无浮夸符号）——
   控制台看，也是 Telegram 群转发的原文（`runtime/log_relay.py` 的 sink 只转带 `event` 的记录，按级别过滤）。

级别即"细节程度"旋钮：`usher_escalate` / `conversation_seed` / `schedule`=DEBUG（开发时想在群里看到的三件事）；
`usher_absorb` / `ingest`=TRACE；`model_call`=TRACE（只留 output + cache 计数，供诊断 cache）；
整段原始转储（原始模型输出等）落 **FIREHOSE**（TRACE 之下一级），让 TRACE 本身保持可读。

刻意保持极简：不引重依赖、不做聚合、不算成本（先记 tokens，定价换算是后话）。
"""
from __future__ import annotations

from loguru import logger

# TRACE 之下再开一级 FIREHOSE(no=3)：给"真·消防栓"式原始转储（整段 prompt / 原始模型输出）用，
# 让 TRACE 本身保留可读性（诊断 cache / prompt 效果 / 回复未命中 filter 时看得清）。幂等注册。
FIREHOSE = "FIREHOSE"
try:
    logger.level(FIREHOSE)
except ValueError:
    logger.level(FIREHOSE, no=3)

# 事件类型 → 日志级别（细节程度旋钮；群转发默认阈值 DEBUG，故 TRACE/FIREHOSE 默认不进群）
_EVENT_LEVELS = {
    "conversation_seed": "DEBUG",   # storyteller seeds a conversation
    "conversation_end": "DEBUG",    # conversation closed (with reason)
    "schedule": "DEBUG",            # conductor picked a speaker, about to fire
    "usher_escalate": "DEBUG",      # user input needs the world to respond -> user_forced
    "usher_absorb": "DEBUG",        # user input absorbed (high volume)
    "player_register": "DEBUG",     # a player claimed a world name via /iam
    "player_iam_rejected": "DEBUG", # /iam rejected (bad name / collision)
    "ingest": "TRACE",              # ingested an external message
    "model_call": "TRACE",          # per-call output + cache counts (readable, for cache diagnosis)
    "model_raw": FIREHOSE,          # raw model output before parsing (filter-miss / prompt-effect)
    "reply_resolve": FIREHOSE,      # {{REPLY}}/内联句柄的内部 id → 被回复消息的 external_id（含超窗→None）
    "compaction": "INFO",           # history compaction
    "error": "ERROR",               # a turn failed, etc.
}
_DEFAULT_LEVEL = "DEBUG"


def _render(kind: str, f: dict) -> str:
    """把事件渲染成一行 `kind key=value ...`：英文键、内容原样、无浮夸符号。

    字符串值含换行→另起一行原样输出；含空格或空串→加引号；其余裸写。
    """
    if not f:
        return kind
    parts = []
    for k, v in f.items():
        if isinstance(v, str):
            if "\n" in v:
                parts.append(f"{k}=\n{v}")
            elif v == "" or " " in v:
                parts.append(f'{k}="{v}"')
            else:
                parts.append(f"{k}={v}")
        else:
            parts.append(f"{k}={v}")
    return f"{kind} " + " ".join(parts)


def log_event(kind: str, **fields) -> None:
    """发一条结构化事件。None 值省略；级别按 _EVENT_LEVELS 选。"""
    clean = {k: v for k, v in fields.items() if v is not None}
    level = _EVENT_LEVELS.get(kind, _DEFAULT_LEVEL)
    # event=kind 进 extra → 群转发 sink 靠它识别；各字段也进 extra 供将来 fold
    logger.bind(event=kind, **clean).log(level, _render(kind, clean))


def log_model_raw(source: str, raw: str, **fields) -> None:
    """在**任何模型输出点**记录原始输出（FIREHOSE）——generator / usher / storyteller /
    conductor / compaction 都用它。source 标出是谁的调用；诊断 filter 未命中 / prompt 效果。
    """
    log_event("model_raw", source=source, raw=raw, **fields)
