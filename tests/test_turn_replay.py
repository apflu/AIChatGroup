"""M0 验收：MockGateway 脚本化 2-Agent 对话，warm 调用命中 cache_read。"""
from aichatgroup.domain import Agent, RoomState, WorldBook
from aichatgroup.message.generator import run_turn
from aichatgroup.io.gateway import MockGateway


def _setup():
    world = WorldBook(
        bible="热闹的酒馆世界，人来人往。" * 4,
        rules="遵守世界书；管理员在场。" * 4,
    )
    room = RoomState(long_term_summary="今天是集市日。", objective_relations="小丸子与阿福是老友。")
    alice = Agent(id="a1", name="小丸子", model_id="claude-opus-4-8",
                  base_prompt="活泼吵闹的 NPC。")
    bob = Agent(id="a2", name="阿福", model_id="claude-sonnet-5",
                base_prompt="沉稳的 NPC。")

    gw = MockGateway()
    gw.push_script("小丸子", [
        '大家好呀！{{SEPARATOR}}今天真热闹\n{{MEMORY}}{"mood": "兴奋"}',
        '我先去逛逛~',
    ])
    gw.push_script("阿福", [
        '来啦。{{SEPARATOR}}慢点跑',
        '等等我。',
    ])
    return world, room, alice, bob, gw


def test_scripted_conversation_applies_to_room():
    world, room, alice, bob, gw = _setup()
    run_turn(gw, world, room, alice)
    run_turn(gw, world, room, bob)

    # 气泡进入共享历史
    speakers = [m.speaker for m in room.history]
    assert speakers == ["小丸子", "小丸子", "阿福", "阿福"]
    assert room.history[0].text == "大家好呀！"
    # 记忆增量合并进私有快照
    assert "兴奋" in room.memory["a1"]
    assert "a2" not in room.memory  # 阿福本回合无记忆增量


def test_warm_calls_hit_cache_read():
    world, room, alice, bob, gw = _setup()
    usages = []
    # 交替发言若干回合
    for agent in (alice, bob, alice, bob):
        r = run_turn(gw, world, room, agent)
        usages.append(r.usage)

    # 首回合冷启动：写入缓存
    assert usages[0].cache_creation_input_tokens > 0
    assert usages[0].cache_read_input_tokens == 0

    # 第二回合起：共享前缀（世界书+长期摘要+已有历史）命中缓存读
    assert usages[1].cache_read_input_tokens > 0

    # 后续每个 warm 回合都应有缓存读命中
    assert all(u.cache_read_input_tokens > 0 for u in usages[1:])
