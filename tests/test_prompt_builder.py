from aichatgroup.domain import Agent, RoomState, WorldBook
from aichatgroup.message.prompt import build_prompt


def _fixture():
    world = WorldBook(bible="这是一个热闹的酒馆世界。", rules="遵守世界书；有管理员。")
    room = RoomState(long_term_summary="战争刚结束。", objective_relations="A 与 B 是兄弟。")
    room.append("小丸子", "大家好呀")
    room.append("阿福", "来啦来啦")
    agent = Agent(id="a1", name="小丸子", model_id="claude-opus-4-8",
                  base_prompt="你是一名 NPC。", character_card="活泼、爱吵闹。")
    return world, room, agent


def test_system_has_two_cached_layers():
    world, room, agent = _fixture()
    system, _ = build_prompt(world, room, agent)
    assert len(system) == 2
    # 两个 system 块都设了缓存断点（第0层、第1层）
    assert all(b["cache_control"] == {"type": "ephemeral"} for b in system)
    assert "世界观圣经" in system[0]["text"]
    assert "前情提要" in system[1]["text"]


def test_history_and_tail_layout():
    world, room, agent = _fixture()
    _, messages = build_prompt(world, room, agent, conductor_instruction="制造一点张力")
    # 2 条历史 + 1 条尾部
    assert len(messages) == 3
    # 仅最后一条历史消息挂缓存断点（滚动 breakpoint 3）
    assert isinstance(messages[0]["content"], str)                 # 非末条历史 → 纯文本
    assert isinstance(messages[1]["content"], list)                # 末条历史 → 带缓存块
    assert messages[1]["content"][0]["cache_control"] == {"type": "ephemeral"}
    # 尾部不缓存
    assert isinstance(messages[2]["content"], str)
    assert "cache_control" not in messages[2]["content"]


def test_tail_contains_persona_memory_director():
    world, room, agent = _fixture()
    room.memory["a1"] = '{"notes": "上一轮很热闹"}'
    _, messages = build_prompt(world, room, agent, conductor_instruction="制造一点张力")
    tail = messages[-1]["content"]
    assert "扮演的角色是「小丸子」" in tail
    assert "活泼、爱吵闹。" in tail          # 角色卡
    assert "上一轮很热闹" in tail            # 私有记忆
    assert "制造一点张力" in tail            # 导演指令
    assert "{{MEMORY}}" in tail             # 输出契约


def test_empty_history_still_has_tail():
    world, _, agent = _fixture()
    empty = RoomState()
    _, messages = build_prompt(world, empty, agent)
    assert len(messages) == 1
    assert "扮演的角色是「小丸子」" in messages[0]["content"]
