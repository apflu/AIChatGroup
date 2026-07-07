"""config：.env 行内注释剥离（不误伤 alias#model 里的 #）。"""
from aichatgroup.config import Settings, _strip_inline_comment


def test_strip_inline_comment_basic():
    assert _strip_inline_comment("value   # 注释") == "value"
    assert _strip_inline_comment("value\t# 注释") == "value"


def test_strip_preserves_hash_in_value():
    # provider_alias#model 里紧挨的 # 不是注释，必须保留
    assert _strip_inline_comment("aistudio#gemini-3.1-flash-lite   # 便宜") == \
        "aistudio#gemini-3.1-flash-lite"
    assert _strip_inline_comment("clwd#claude-sonnet-5") == "clwd#claude-sonnet-5"


def test_strip_leaves_quoted_value_alone():
    assert _strip_inline_comment('"a # b"') == '"a # b"'


def test_load_dotenv_strips_inline_comment(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "AICG_MODEL_DIRECTOR=aistudio#gemini-3.1-flash-lite      # 调度用便宜模型\n"
        "ANTHROPIC_API_KEY=sk-real-key\n",
        encoding="utf-8",
    )
    # 隔离：确保这两个 key 不在环境里，setdefault 才会写入
    monkeypatch.delenv("AICG_MODEL_DIRECTOR", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    s = Settings.from_env(env)
    assert s.director_model == "aistudio#gemini-3.1-flash-lite"  # 注释已剥
    assert s.anthropic_api_key == "sk-real-key"
