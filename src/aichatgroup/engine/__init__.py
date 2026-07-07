"""引擎运行层：输出解析、气泡节奏、发言回合执行、历史压缩。"""
from .compaction import CompactionResult, maybe_compact
from .pacing import infer_pause, resolve_pauses
from .parsing import parse_turn_output
from .turn import merge_memory, run_turn

__all__ = [
    "parse_turn_output",
    "infer_pause",
    "resolve_pauses",
    "run_turn",
    "merge_memory",
    "maybe_compact",
    "CompactionResult",
]
