"""领域数据结构。

M0 共享全知设计：所有 Agent 共用同一份 append-only 历史（RoomState.history），
每个 Agent 只有私有记忆快照（RoomState.memory[agent_id]）沉在尾部、每轮可变。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .markers import USER_TAG
from ..prompts import render as render_prompt


@dataclass
class WorldBook:
    """第 0 层：世界观圣经 + 群聊规则（几乎不变，放最前，命中共享缓存）。"""

    bible: str
    rules: str

    def render(self) -> str:
        return render_prompt("world", bible=self.bible.strip(), rules=self.rules.strip())


@dataclass
class PacingConfig:
    """气泡间停顿的推断参数 —— 按角色配置，与性格接驳。

    停顿 = 模拟「打完上一条、下一条冒出来」之间的间隔（M1 Telegram 适配层会据此
    发 typing 提示 + sleep）。缺省按下一条气泡长度推断；模型也可在
    `{{SEPARATOR:秒}}` 里显式指定，显式值经 explicit_scale 缩放后采用。

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
        parts.append(render_prompt("persona", name=self.name))
        if self.character_card.strip():
            parts.append(self.character_card.strip())
        return "\n\n".join(parts)


@dataclass
class ContentPart:
    """消息内容的一段。动作/语言分离就落在这（未来可加 sticker/tool_* kind）。"""

    kind: str          # "speech" | "gesture"(神态) | "beat"(举动) | "action"(旧别名) | "sticker"
    text: str


# 动作类 kind：喂给模型的历史里一律渲成中文括号（形态与旧 "action" 一致 → 缓存不变）。
# 神态/举动的分野只在**聊天流投递**时体现（gesture 隐、beat 交旁白），历史层不区分。
_ACTION_KINDS = ("gesture", "beat", "action")


def render_parts(parts: "list[ContentPart]") -> str:
    """把 parts 渲染成给模型看/入历史的文本：动作用中文括号、贴纸标注、语言裸文本。

    纯 speech 时输出 == 语言原文 → 与旧 `text` 逐字节一致，保共享缓存前缀不变式。
    注意这是**历史/上下文**渲染；发到聊天流的内容由 orchestrator 按 kind 分流，另行处理。
    """
    out = []
    for p in parts:
        if p.kind in _ACTION_KINDS:
            out.append(f"（{p.text}）")
        elif p.kind == "sticker":
            out.append(f"[贴纸:{p.text}]")
        else:
            out.append(p.text)
    return "".join(out)


@dataclass
class Message:
    """共享历史里的一条消息 —— 粒度 = 一条气泡（或一条人类消息 / sticker）。

    id 是房间内**稳定单调**的标识（有 store 时来自 messages.id；离线时由 RoomState 计数器给），
    既是持久主键、也是模型回复寻址用的 handle。speaker 是显示名（角色名或人类 PL 名）。
    parts 承载动作/语言分离；reply_to 指向另一条 Message.id；meta 是开放逃生舱
    （external_id / turn / pause_before / model / ts …）。
    """

    id: int
    speaker: str
    parts: list[ContentPart] = field(default_factory=list)
    author_kind: str = "agent"          # agent | human | system
    reply_to: int | None = None
    meta: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        """便利属性：拼接全部 speech 段（供日志 / TTS / 兼容）。不含动作。"""
        return "".join(p.text for p in self.parts if p.kind == "speech")

    def render(self, reply_note: str = "") -> str:
        """序列化进历史：`⟦id⟧ <user> [speaker] （回…）（动作）语言`。

        `⟦id⟧` 是稳定 handle，模型据此用 `{{REPLY:id}}` 回复某条。人类玩家的行在名字**前**加
        `<user>` 种类 tag（AI 角色行不加、保持纯净）——标出"这是人不是 AI"，且刺目难伪造/难被回显。
        reply_note 由 builder 传入（被回复消息的定长引用），render 自身不查别的消息。
        id/speaker/parts/author_kind 跨 agent 相同、跨轮稳定 → 前缀逐字节一致，保共享缓存不变式。
        """
        note = f"{reply_note} " if reply_note else ""
        tag = f"{USER_TAG} " if self.author_kind == "human" else ""
        return f"⟦{self.id}⟧ {tag}[{self.speaker}] {note}{render_parts(self.parts)}"


# 迁移期别名：保住公共导出与旧引用，一个周期后可移除。
ChatMessage = Message


@dataclass
class RoomState:
    """一个群聊房间的会话状态。"""

    # 第 1 层：长期摘要 + 客观关系图谱（周期性/压缩时重写）
    long_term_summary: str = ""
    objective_relations: str = ""
    # 第 2 层：近期共享历史（append-only）
    history: list[Message] = field(default_factory=list)
    # 第 3 层尾部：每 Agent 私有记忆快照（agent_id -> 文本），每轮整块替换
    memory: dict[str, str] = field(default_factory=dict)
    # 离线场景（无 store）铸造消息 id 的计数器；有 store 时由传入的显式 id 决定。
    _next_id: int = field(default=1, repr=False)

    def __post_init__(self) -> None:
        # 从已有历史（如 store 载入）同步计数器，避免 id 冲突。
        if self.history:
            self._next_id = max(m.id for m in self.history) + 1

    def render_layer1(self) -> str:
        parts = []
        if self.long_term_summary.strip():
            parts.append(render_prompt("layer1_summary", summary=self.long_term_summary.strip()))
        if self.objective_relations.strip():
            parts.append(render_prompt("layer1_relations", relations=self.objective_relations.strip()))
        return "\n\n".join(parts) if parts else "(暂无长期摘要)"

    def append(
        self,
        speaker: str,
        text: str | None = None,
        *,
        parts: list[ContentPart] | None = None,
        id: int | None = None,
        author_kind: str = "agent",
        reply_to: int | None = None,
        meta: dict | None = None,
    ) -> Message:
        """追加一条消息，返回它。

        id 省略时由内部计数器铸造（离线/测试）；有 store 时调用方传入 store 分配的 id。
        parts 省略时按 text 包成单个 speech 段（Phase A 的等价行为）。
        """
        if id is None:
            id = self._next_id
            self._next_id += 1
        else:
            self._next_id = max(self._next_id, id + 1)
        if parts is None:
            parts = [ContentPart(kind="speech", text=text or "")]
        msg = Message(
            id=id, speaker=speaker, parts=parts,
            author_kind=author_kind, reply_to=reply_to, meta=meta or {},
        )
        self.history.append(msg)
        return msg


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
