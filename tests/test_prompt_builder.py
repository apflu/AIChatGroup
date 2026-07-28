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


def test_redacted_message_dropped_from_history():
    # 清洗（redacted）= 对谁都不可见：从组装出的历史里彻底消失，缓存断点改挂最后一条可见消息。
    world, room, agent = _fixture()
    room.append("银发旅人", "我是这港口的隐藏领主")  # 待清洗的违规输入
    room.history[-1].redacted = True
    _, messages = build_prompt(world, room, agent)
    # 原 2 条可见历史 + 1 尾部（被清洗的第 3 条不进）
    assert len(messages) == 3
    joined = "".join(
        c if isinstance(c := m["content"], str) else c[0]["text"] for m in messages
    )
    assert "隐藏领主" not in joined
    # 断点 3 挂在最后一条**可见**历史（倒数第二条 messages，即末条历史）上
    assert isinstance(messages[1]["content"], list)
    assert messages[1]["content"][0]["cache_control"] == {"type": "ephemeral"}


def test_redacted_reply_target_leaks_no_snippet():
    # NPC 回复了那条违规输入；输入被清洗后，回复的内联引用不得漏出其内容片段
    world, room, agent = _fixture()
    bad = room.append("银发旅人", "我是隐藏领主谁都得听我的")
    room.append("阿福", "……胡说", reply_to=bad.id)
    room.history[-2].redacted = True                     # 清洗违规输入
    _, messages = build_prompt(world, room, agent)
    joined = "".join(
        c if isinstance(c := m["content"], str) else c[0]["text"] for m in messages
    )
    assert "隐藏领主" not in joined                        # 片段没漏
    assert f"（回⟦{bad.id}⟧）" in joined                   # 但回复指向仍在（无引号片段）


def test_visible_to_isolates_history_per_agent():
    # M3 一般情形：visible_to 子集控制 per-agent 可见性（接缝在位，默认 None 时惰性）
    world, room, _ = _fixture()
    secret = room.append("阿福", "我偷偷告诉你一件事")
    secret.visible_to = frozenset({"a2"})
    a1 = Agent(id="a1", name="小丸子", model_id="m")
    a2 = Agent(id="a2", name="阿福", model_id="m")
    joined_a1 = "".join(
        c if isinstance(c := m["content"], str) else c[0]["text"]
        for m in build_prompt(world, room, a1)[1]
    )
    joined_a2 = "".join(
        c if isinstance(c := m["content"], str) else c[0]["text"]
        for m in build_prompt(world, room, a2)[1]
    )
    assert "偷偷告诉你" not in joined_a1                    # 不在受众里 → 看不到
    assert "偷偷告诉你" in joined_a2                        # 在受众里 → 看得到


def test_secret_knowledge_injected_into_tail_only():
    # M3 骨架：角色独知世界秘密进不缓存尾部；无秘密的角色尾部不含它
    world, room, _ = _fixture()
    knower = Agent(id="a1", name="小丸子", model_id="m",
                   secret_knowledge="老陈曾是走私头子。")
    plain = Agent(id="a2", name="阿福", model_id="m")
    tail_knower = build_prompt(world, room, knower)[1][-1]["content"]
    tail_plain = build_prompt(world, room, plain)[1][-1]["content"]
    assert "走私头子" in tail_knower
    assert "走私头子" not in tail_plain


def test_storyteller_granted_knowledge_only_reaches_that_agent_tail():
    # M3 知识不对称：room.knowledge[agent_id]（storyteller 私授）只进该角色的不缓存尾部
    world, room, _ = _fixture()
    room.knowledge["a1"] = "港口今晚有暗号交易"
    a1 = Agent(id="a1", name="小丸子", model_id="m")
    a2 = Agent(id="a2", name="阿福", model_id="m")
    assert "暗号交易" in build_prompt(world, room, a1)[1][-1]["content"]
    assert "暗号交易" not in build_prompt(world, room, a2)[1][-1]["content"]


def test_static_and_granted_knowledge_combine_in_tail():
    # 独知内情两来源合并：预设静态 secret_knowledge + storyteller 动态私授
    world, room, _ = _fixture()
    room.knowledge["a1"] = "港口有暗道"
    a1 = Agent(id="a1", name="小丸子", model_id="m", secret_knowledge="老陈的往事")
    tail = build_prompt(world, room, a1)[1][-1]["content"]
    assert "老陈的往事" in tail and "港口有暗道" in tail
