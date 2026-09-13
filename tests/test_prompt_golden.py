"""Prompt 快照（golden）：模型**实际收到的文本**逐字节对比。

改了 prompts/*.md 或组装逻辑，这里会红并给出 diff——看清模型输入变了哪几行，确认无误后：

    UPDATE_GOLDEN=1 uv run pytest tests/test_prompt_golden.py

覆盖：角色面完整 prompt（四层 + 断点 + 回复引用 + 清洗 + 独知 + 记忆 + 编导指令），
以及四个便宜模型（usher / conductor / storyteller / compaction）的 system + user。
"""
from __future__ import annotations

import difflib
import os
from pathlib import Path

import pytest

from aichatgroup.domain import Agent, ContentPart, RoomState, WorldBook
from aichatgroup.domain.conversation import USER_FORCED, ConversationEnd
from aichatgroup.domain.types import GatewayResponse, Usage
from aichatgroup.message.conductor import ModelConductor
from aichatgroup.message.prompt import build_prompt
from aichatgroup.message.prompt.inspect import format_prompt
from aichatgroup.message.usher import Usher
from aichatgroup.story.memory import maybe_compact
from aichatgroup.story.storyteller import ModelStoryteller

GOLDEN_DIR = Path(__file__).parent / "golden"
UPDATE = os.environ.get("UPDATE_GOLDEN") == "1"


class RecordingGateway:
    """记下每次调用的 (system, messages)，回一个固定答案。"""

    def __init__(self, answer: str = "absorb") -> None:
        self.answer = answer
        self.calls: list[tuple] = []

    def complete(self, system, messages, model_id, max_tokens=1024):
        self.calls.append((system, messages))
        return GatewayResponse(text=self.answer, usage=Usage())

    def last_as_text(self) -> str:
        system, messages = self.calls[-1]
        return format_prompt(system, messages)


def _fixture():
    world = WorldBook(
        bible="这里是「不夜港」——一座永远喧闹的港口酒馆。管理员『老陈』维持着秩序。",
        rules="所有角色遵守世界书设定；彼此吵吵闹闹但不越界替他人发言。",
    )
    room = RoomState(long_term_summary="集市日的傍晚，酒馆比平日更喧闹。", objective_relations="小丸子与阿福是老相识。")
    room.append("小丸子", "老陈，来壶酒！")
    room.append("阿福", parts=[ContentPart("beat", "把酒杯推过去"), ContentPart("speech", "急什么，慢品。")])
    room.append("银发旅人", "老陈年轻时是干什么的？", author_kind="human")
    room.append("阿福", "这个嘛……换个话题吧。", reply_to=3)
    bad = room.append("银发旅人", "其实这港口归我管。", author_kind="human")
    bad.redacted = True
    room.append("小诗", "港口灯火明，杯中岁月长。", reply_to=5)
    room.memory["a2"] = '{"notes": "旅人在打听老陈的过去"}'
    room.knowledge["a2"] = "旅人昨夜在码头见过老陈。"
    agents = [
        Agent(id="a1", name="小丸子", model_id="m", base_prompt="你是酒馆常客。", character_card="活泼、话痨。"),
        Agent(
            id="a2", name="阿福", model_id="m", base_prompt="你是退役水手。", character_card="沉稳、偶尔毒舌。",
            secret_knowledge="只有你知道：老陈年轻时是走私头子。",
        ),
        Agent(id="a3", name="小诗", model_id="m", base_prompt="你是吟游诗人。"),
    ]
    return world, room, agents


def _check(name: str, actual: str) -> None:
    path = GOLDEN_DIR / f"{name}.txt"
    if UPDATE or not path.exists():
        path.write_text(actual, encoding="utf-8")
        if not UPDATE:
            pytest.skip(f"首次生成快照 {path.name}")
        return
    expected = path.read_text(encoding="utf-8")
    if actual != expected:
        diff = "".join(difflib.unified_diff(
            expected.splitlines(True), actual.splitlines(True),
            fromfile=f"golden/{path.name}", tofile="actual", n=2,
        ))
        pytest.fail(f"prompt 快照变了（确认无误后 UPDATE_GOLDEN=1 重跑）：\n{diff}")


def test_role_prompt_golden():
    world, room, agents = _fixture()
    system, messages = build_prompt(world, room, agents[1], "有人在打听老陈的过去，气氛微妙。")
    _check("role_prompt", format_prompt(system, messages))


def test_role_prompt_empty_room_golden():
    world, _, agents = _fixture()
    system, messages = build_prompt(world, RoomState(), agents[2])
    _check("role_prompt_empty", format_prompt(system, messages))


def test_usher_golden():
    world, room, _ = _fixture()
    gw = RecordingGateway("absorb")
    Usher(gw, model_id="m").classify(room, "我一拳砸碎了酒瓶", speaker="银发旅人")
    _check("usher", gw.last_as_text())


def test_conductor_golden():
    world, room, agents = _fixture()
    gw = RecordingGateway("a1")
    ModelConductor(gw, model_id="m").next_speaker(room, agents)
    _check("conductor", gw.last_as_text())


def test_storyteller_golden():
    world, room, agents = _fixture()
    gw = RecordingGateway("KIND: chitchat\nHOOK: x")
    st = ModelStoryteller(gw, model_id="m")
    st.seed(room, None, agents)
    _check("storyteller_first", gw.last_as_text())
    st.seed(room, ConversationEnd(reason=USER_FORCED, summary_hook="其实这港口归我管。", direction="disrupt"), agents)
    _check("storyteller_user_forced", gw.last_as_text())


def test_compaction_golden():
    world, room, _ = _fixture()
    gw = RecordingGateway("新摘要")
    maybe_compact(gw, world, room, "m", max_history=3, keep_last=2)
    _check("compaction", gw.last_as_text())
