"""生成：一个角色的一个发言回合 → 气泡草稿 + 节奏 + 记忆增量。"""
from .parsing import ParsedBubble, parse_turn_output
from .turn import (
    GeneratedTurn,
    apply_turn,
    finish_turn,
    generate_turn,
    merge_memory,
    prepare_turn,
    run_turn,
)

__all__ = [
    "ParsedBubble",
    "parse_turn_output",
    "GeneratedTurn",
    "prepare_turn",
    "finish_turn",
    "generate_turn",
    "apply_turn",
    "merge_memory",
    "run_turn",
]
