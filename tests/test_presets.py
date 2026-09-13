"""Preset 加载：世界书 / 角色卡 / 房间种子 / transport 段与 *_env 解析（telegram 由其 transport 自取）。"""
import json

from aichatgroup.io.transport.telegram import TelegramConfig
from aichatgroup.presets import load_preset


def _write(tmp_path, data):
    p = tmp_path / "room.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def test_load_preset_builds_domain_objects(tmp_path, monkeypatch):
    monkeypatch.setenv("TG_OBS", "obs-token")
    monkeypatch.setenv("TG_A1", "a1-token")
    data = {
        "room_key": "buyeport",
        "world": {"bible": "不夜港。", "rules": "遵守设定。"},
        "room": {"long_term_summary": "傍晚很热闹。", "objective_relations": "老相识。"},
        "agents": [
            {
                "id": "a1", "name": "小丸子", "model_id": "claude-opus-4-8",
                "base_prompt": "常客。", "character_card": "活泼。",
                "pacing": {"base_pause_s": 0.2, "per_char_s": 0.03, "explicit_scale": 0.6},
                "bot_token_env": "TG_A1",
            },
            {"id": "a2", "name": "阿福", "model_id": "claude-sonnet-5"},
        ],
        "telegram": {"observer_token_env": "TG_OBS", "chat_id": "-100123"},
    }
    preset = load_preset(_write(tmp_path, data))

    assert preset.room_key == "buyeport"
    assert preset.world.bible == "不夜港。"
    assert preset.seed_summary == "傍晚很热闹。"
    assert preset.seed_relations == "老相识。"

    assert [a.id for a in preset.agents] == ["a1", "a2"]
    a1 = preset.agents[0]
    assert a1.name == "小丸子"
    assert a1.pacing.explicit_scale == 0.6
    # a2 无 pacing → 默认
    assert preset.agents[1].pacing.base_pause_s == 0.4

    # 平台段原样保留、*_env 从环境解析；引擎不认识的角色键进 agent_options
    assert preset.transports["telegram"] == {"observer_token": "obs-token", "chat_id": "-100123"}
    assert preset.agent_options["a1"] == {"bot_token": "a1-token"}
    assert preset.agent_options["a2"] == {}
    # telegram transport 自己从预设里取它要的
    tg = TelegramConfig.from_preset(preset)
    assert tg.observer_token == "obs-token"
    assert tg.chat_id == "-100123"
    assert tg.agent_tokens == {"a1": "a1-token"}        # a2 未配置 → 不在里面
    assert tg.complete


def test_missing_env_tokens_are_none(tmp_path):
    data = {
        "world": {"bible": "x"},
        "agents": [{"id": "a1", "name": "n", "model_id": "m", "bot_token_env": "NOPE"}],
    }
    preset = load_preset(_write(tmp_path, data))
    assert preset.room_key == "default"
    assert preset.agent_options["a1"] == {"bot_token": None}
    tg = TelegramConfig.from_preset(preset)
    assert tg.observer_token is None
    assert tg.agent_tokens == {}
    assert not tg.complete


def test_transports_block_and_generic_players(tmp_path, monkeypatch):
    # 新式：transports.<name> 段 + players 用 channel/external_id（不再绑 telegram）
    monkeypatch.setenv("PL_X", "42")
    data = {
        "world": {"bible": "x"},
        "agents": [{"id": "a1", "name": "n", "model_id": "m", "bot_token": "direct-token"}],
        "transports": {"telegram": {"observer_token_env": "NOPE", "chat_id": -1}},
        "players": [
            {"name": "旅人", "channel": "foundry", "external_id_env": "PL_X"},
            {"name": "旧式", "telegram_id": 7},
        ],
    }
    preset = load_preset(_write(tmp_path, data))
    assert preset.transports["telegram"] == {"observer_token": None, "chat_id": -1}
    assert TelegramConfig.from_preset(preset).chat_id == "-1"
    assert TelegramConfig.from_preset(preset).agent_tokens == {"a1": "direct-token"}
    assert (preset.players[0].channel, preset.players[0].external_id) == ("foundry", "42")
    assert (preset.players[1].channel, preset.players[1].external_id) == ("telegram", "7")
