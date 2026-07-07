"""Preset 加载：世界书 / 角色卡 / 房间种子 / telegram *_env 解析。"""
import json

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

    # telegram *_env 从环境解析
    assert preset.telegram.observer_token == "obs-token"
    assert preset.telegram.chat_id == "-100123"
    assert preset.telegram.agents["a1"].bot_token == "a1-token"
    assert preset.telegram.agents["a2"].bot_token is None  # 未配置 → None


def test_missing_env_tokens_are_none(tmp_path):
    data = {
        "world": {"bible": "x"},
        "agents": [{"id": "a1", "name": "n", "model_id": "m", "bot_token_env": "NOPE"}],
    }
    preset = load_preset(_write(tmp_path, data))
    assert preset.room_key == "default"
    assert preset.telegram.observer_token is None
    assert preset.telegram.agents["a1"].bot_token is None
