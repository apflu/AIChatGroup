"""会话层的共享词汇（domain 内核）—— storyteller ⇄ conductor 的交接数据。

一段 **conversation**（会话）是"一段有形状的对话：起→展开→僵/高潮→收"。它跨越若干
beat / turn / 气泡，是 storyteller 的落子粒度（详见 docs/milestone/M2.md）。

两个数据契约走**相反方向**，构成一个跨会话的循环（seed → run → end → reseed）：
- `ConversationIntent`：storyteller → conductor，为下一段会话播种意图。
- `ConversationEnd`  ：conductor → storyteller，报告一段会话如何收束（**必带 reason**）。

放 domain：它们是**两平面 + runtime 的共享词汇**，message 与 story 都依赖它、彼此不直接 import。
字段是"够用的骨架"，重 storyteller（M2-C）接上来时可再拧，但 reason 词表是机器契约，别漂。
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ── 意图种类（storyteller 播种时选一）──────────────────────────────
CHITCHAT = "chitchat"              # 闲聊，无自然高潮，靠 length_budget 收
DEVELOP_PLOT = "develop_plot"      # 推进某条剧情线
RESOLVE_TENSION = "resolve_tension"  # 化解/引爆积压的张力
INTENT_KINDS = frozenset({CHITCHAT, DEVELOP_PLOT, RESOLVE_TENSION})

# ── 结束原因（conductor 检测到会话收束时必报其一）──────────────────
# 原因决定 storyteller 的下一手，是 M2 会话循环的关键机器契约（见 M2.md §4 表）。
LULL = "lull"                      # 闲聊耗尽、没人有新话 → 抛新钩子/换话题
DEADLOCK = "deadlock"              # 张力卡死、原地打转（僵局）→ 抛压力/转折打破
INTENT_FULFILLED = "intent_fulfilled"  # 意图达成 → 收束进下一段
USER_FORCED = "user_forced"        # 用户关键输入强制收束 → 把用户输入并进新意图
MAX_LENGTH = "max_length"          # 超长硬兜底 → 强制收，防拖死
END_REASONS = frozenset({LULL, DEADLOCK, INTENT_FULFILLED, USER_FORCED, MAX_LENGTH})


@dataclass
class ConversationIntent:
    """storyteller → conductor：为下一段会话播种的意图。

    hook 是"这段空气里悬着什么"——注入前台 agent 尾部（走 conductor_instruction 不缓存槽）的
    压力指令。length_budget 是粗略预期 beat 数（尤其闲聊，无自然高潮时靠它收束）。
    """

    kind: str = CHITCHAT
    hook: str = ""
    focus: list[str] = field(default_factory=list)   # 可选：点名相关角色 id
    length_budget: int | None = None                 # 粗略预期 beat 数
    tension_target: float | None = None              # 期望张力水位（0~1）


@dataclass
class ConversationEnd:
    """conductor → storyteller：一段会话如何收束。

    reason 是机器契约（∈ END_REASONS），决定 storyteller 下一手。direction 是 usher 在
    `user_forced` 时附带的方向标签（advance/disrupt/probe/swerve），供 storyteller 定向回应用户。
    summary_hook 是"这段发生了什么"的一句话，供 storyteller 记忆 + 播种连贯的下一段。
    """

    reason: str
    tension: float = 0.0
    summary_hook: str = ""
    direction: str = ""              # 仅 user_forced：usher 的方向标签
