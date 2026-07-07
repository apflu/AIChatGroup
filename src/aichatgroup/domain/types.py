"""领域数据结构。

M0 共享全知设计：所有 Agent 共用同一份 append-only 历史（RoomState.history），
每个 Agent 只有私有记忆快照（RoomState.memory[agent_id]）沉在尾部、每轮可变。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class WorldBook:
    """第 0 层：世界观圣经 + 群聊规则（几乎不变，放最前，命中共享缓存）。"""

    bible: str
    rules: str

    def render(self) -> str:
        return f"# 世界观圣经\n{self.bible.strip()}\n\n# 群聊规则\n{self.rules.strip()}"


@dataclass
class PacingConfig:
    """气泡间停顿的推断参数 —— 按角色配置，与性格接驳。

    停顿 = 模拟「打完上一条、下一条冒出来」之间的间隔（M1 Telegram 适配层会据此
    发 typing 提示 + sleep）。缺省按下一条气泡长度推断；模型也可在
    `<<SEPARATOR:秒>>` 里显式指定，显式值经 explicit_scale 缩放后采用。

    这是「让推断与角色性格接驳」的第一个落点：急性子把 per_char_s / explicit_scale
    调小、慢性子调大。后续其他涉及推断的行为（语速、话痨程度……）应循同一模式，
    把可调 factor 存进角色设定里。
    """

    base_pause_s: float = 0.4      # 起步固定停顿
    per_char_s: float = 0.05       # 每字符增加的停顿（打字速度的倒数）
    min_pause_s: float = 0.3       # 推断停顿下限
    max_pause_s: float = 6.0       # 停顿上限（含显式）
    explicit_scale: float = 1.0    # 对模型显式停顿的缩放


@dataclass
class Agent:
    """一个角色。M0 里每个 Agent 绑定一个 model_id，可混用不同模型。"""

    id: str
    name: str
    model_id: str
    # RisuAI 式层级：全局 base_prompt → 角色卡人设/示例对话
    base_prompt: str = ""
    character_card: str = ""
    # 与性格接驳的推断配置（目前只有停顿；后续可扩展更多可调 factor）
    pacing: "PacingConfig" = field(default_factory=lambda: PacingConfig())

    def render_persona(self) -> str:
        parts = []
        if self.base_prompt.strip():
            parts.append(self.base_prompt.strip())
        parts.append(f"你现在扮演的角色是「{self.name}」。")
        if self.character_card.strip():
            parts.append(self.character_card.strip())
        return "\n\n".join(parts)


@dataclass
class ChatMessage:
    """共享历史里的一条消息。speaker 是显示名（角色名或人类 PL 名）。"""

    speaker: str
    text: str

    def render(self) -> str:
        return f"[{self.speaker}] {self.text}"


@dataclass
class RoomState:
    """一个群聊房间的会话状态。"""

    # 第 1 层：长期摘要 + 客观关系图谱（周期性/压缩时重写）
    long_term_summary: str = ""
    objective_relations: str = ""
    # 第 2 层：近期共享历史（append-only）
    history: list[ChatMessage] = field(default_factory=list)
    # 第 3 层尾部：每 Agent 私有记忆快照（agent_id -> 文本），每轮整块替换
    memory: dict[str, str] = field(default_factory=dict)

    def render_layer1(self) -> str:
        parts = []
        if self.long_term_summary.strip():
            parts.append(f"# 前情提要\n{self.long_term_summary.strip()}")
        if self.objective_relations.strip():
            parts.append(f"# 客观关系图谱\n{self.objective_relations.strip()}")
        return "\n\n".join(parts) if parts else "(暂无长期摘要)"

    def append(self, speaker: str, text: str) -> None:
        self.history.append(ChatMessage(speaker=speaker, text=text))


@dataclass
class Usage:
    """一次模型调用的 token 计量，用于验证缓存命中。"""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass
class GatewayResponse:
    text: str
    usage: Usage


@dataclass
class TurnResult:
    """一个发言回合的结果。"""

    agent_id: str
    bubbles: list[str]
    memory_delta: dict | None
    usage: Usage
    raw_text: str
    # 每条气泡「发送前应等待」的秒数；pauses[0] 恒为 0.0。M1 发送层消费。
    pauses: list[float] = field(default_factory=list)
