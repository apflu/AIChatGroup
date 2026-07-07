"""M0 演示：脚本化多 Agent 群聊回放，日志展示分层缓存计量。

用法：
  python scripts/replay_demo.py            # 默认 MockGateway，离线、可复现
  python scripts/replay_demo.py --live     # 真实调用 Anthropic（需 ANTHROPIC_API_KEY）
  python scripts/replay_demo.py --turns 6  # 指定回合数

--live 下由各 Agent 绑定的真实模型生成台词；缓存字段来自 Anthropic 返回的 usage。
（注意：过短的前缀低于最小可缓存长度时，真实缓存可能不命中——这是预期，见计划验证节。）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aichatgroup.config import Settings
from aichatgroup.domain import Agent, PacingConfig, RoomState, WorldBook
from aichatgroup.engine import run_turn
from aichatgroup.gateway import AnthropicGateway, MockGateway
from aichatgroup.logging_setup import setup_logging


def build_world() -> WorldBook:
    return WorldBook(
        bible=(
            "这里是「不夜港」——一座永远喧闹的港口酒馆。三教九流在此往来，"
            "水手、商人、吟游诗人与流浪法师同桌而坐。管理员『老陈』维持着秩序。"
        ),
        rules=(
            "所有角色遵守世界书设定，不得凭空造出世界中不存在的事物；"
            "彼此吵吵闹闹但不越界替他人发言；管理员有最终裁量权。"
        ),
    )


def build_agents(settings: Settings) -> list[Agent]:
    return [
        # 急性子：打字快、停顿短
        Agent(id="a1", name="小丸子", model_id=settings.model_opus,
              base_prompt="你是酒馆常客。", character_card="活泼、话痨、爱起哄。",
              pacing=PacingConfig(base_pause_s=0.2, per_char_s=0.03, explicit_scale=0.6)),
        # 慢性子：停顿更长
        Agent(id="a2", name="阿福", model_id=settings.model_sonnet,
              base_prompt="你是退役水手。", character_card="沉稳、爱讲道理、偶尔毒舌。",
              pacing=PacingConfig(base_pause_s=0.8, per_char_s=0.09, explicit_scale=1.5)),
        # 默认节奏
        Agent(id="a3", name="小诗", model_id=settings.model_haiku,
              base_prompt="你是吟游诗人。", character_card="浪漫、爱接话、总想押韵。"),
    ]


def make_mock_gateway(agents: list[Agent], turns: int) -> MockGateway:
    gw = MockGateway()
    scripts = {
        "小丸子": [
            "哟！今天人可真多呀~{{SEPARATOR}}老陈，来壶好酒！\n{{MEMORY}}{\"mood\": \"兴奋\", \"want\": \"喝酒\"}",
            "阿福你又在讲大道理啦？{{SEPARATOR}}哈哈哈",
            "小诗快来一首！",
        ],
        "阿福": [
            "急什么，酒要慢慢品。",
            "年轻人就是毛躁。{{SEPARATOR}}不过……今天是挺热闹。",
            "行吧，听你的。",
        ],
        "小诗": [
            "港口灯火明，杯中岁月长~",
            "让我想想韵脚……",
            "热闹一场终须散，且把今宵付笑谈。\n{{MEMORY}}{\"line\": \"付笑谈\"}",
        ],
    }
    for agent in agents:
        gw.push_script(agent.name, scripts.get(agent.name, [])[: turns])
    return gw


def main() -> int:
    parser = argparse.ArgumentParser(description="AI 群聊 M0 回放演示")
    parser.add_argument("--live", action="store_true", help="真实调用 Anthropic")
    parser.add_argument("--turns", type=int, default=6, help="回合数（默认 6）")
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass

    setup_logging()
    settings = Settings.from_env()
    world = build_world()
    agents = build_agents(settings)
    room = RoomState(
        long_term_summary="集市日的傍晚，酒馆比平日更喧闹。",
        objective_relations="小丸子与阿福是老相识；小诗是新来的吟游诗人。",
    )

    if args.live:
        if not settings.anthropic_api_key:
            print("缺少 ANTHROPIC_API_KEY，无法 --live。", file=sys.stderr)
            return 2
        gateway = AnthropicGateway(api_key=settings.anthropic_api_key)
        director = "现场很热闹，接着这个气氛自然地说几句。"
    else:
        gateway = make_mock_gateway(agents, args.turns)
        director = ""

    print("=" * 60)
    print("不夜港 · 群聊回放（%s）" % ("LIVE" if args.live else "MOCK"))
    print("=" * 60)

    total_read = total_creation = 0
    # 简易 round-robin 调度（真正的 director 调度器在 M1）
    for turn in range(args.turns):
        agent = agents[turn % len(agents)]
        result = run_turn(gateway, world, room, agent,
                          director_instruction=director, max_tokens=settings.max_tokens)
        for bubble, pause in zip(result.bubbles, result.pauses):
            gap = f"   〔停 {pause:.1f}s〕" if pause > 0 else ""
            print(f"  {agent.name}: {bubble}{gap}")
        total_read += result.usage.cache_read_input_tokens
        total_creation += result.usage.cache_creation_input_tokens

    print("-" * 60)
    print(f"累计 cache_read={total_read}  cache_creation={total_creation}")
    print(f"共享历史条数：{len(room.history)}")
    print("私有记忆快照：")
    for agent in agents:
        mem = room.memory.get(agent.id, "(空)")
        print(f"  {agent.name}: {mem}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
