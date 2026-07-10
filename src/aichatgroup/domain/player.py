"""Player —— 一个人类参与者在**某个世界内**的身份。

与 Agent 并列：都是世界里的在场者（Participant），唯一区别是**回合的来源**——Agent 由模型生成，
Player 由人类经 transport 生成。共有的是：世界内稳定 id、世界内名字、可选人设、进共享历史、被
conductor/usher 纳入身份感知。

身份映射锚在**稳定外部 id**（如 telegram `from_user.id`），不锚显示名——显示名会变、还在别处复用。
映射按世界（room_id）分区，见 runtime/players.py::PlayerRegistry。
"""
from __future__ import annotations

from dataclasses import dataclass

# 未注册者的默认世界名（陌生人进了酒馆）。注册（/iam）后升级为正式世界名。
STRANGER_NAME = "陌生人"

# 世界名净化：玩家名是**不可信输入**，会被原样渲染进模型看的结构化流 `[{speaker}]`。
# 真正必须做的校验是**防伪造归属**——禁掉能撬开归属/句柄/标记的字符，而非追无穷的唯一性。
_NAME_MAX = 24
# 结构位字符：`[]` 名字括号、`⟦⟧` 消息句柄、`<>` 种类 tag、`{}` 控制标记。全禁 → 名字进不了任何控制位。
_FORBIDDEN = set("[]<>{}⟦⟧⟨⟩")


def sanitize_player_name(raw: str) -> str:
    """净化世界名，非法则抛 ValueError。折叠内部空白（顺带清掉换行/制表），禁结构位字符、限长。"""
    name = " ".join(raw.split())          # 折叠所有空白（含 \n\r\t）+ 去首尾
    if not name:
        raise ValueError("名字不能为空")
    if len(name) > _NAME_MAX:
        raise ValueError(f"名字过长（上限 {_NAME_MAX} 字）")
    bad = _FORBIDDEN & set(name)
    if bad:
        raise ValueError(f"名字含非法字符：{''.join(sorted(bad))}")
    return name


@dataclass
class Player:
    """一个玩家在某世界的身份。id 由 channel:external_id 派生（稳定、离线也可用）。"""

    name: str                    # 世界内显示名（进历史的 speaker）
    persona: str = ""            # 世界内人设（供 AI 角色理解"这人是谁"，非生成 prompt）
    channel: str = ""            # 外部渠道，如 "telegram"
    external_id: str = ""        # 该渠道下的稳定用户 id（如 from_user.id）

    @property
    def id(self) -> str:
        return f"{self.channel}:{self.external_id}"
