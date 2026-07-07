"""多 provider 网关：翻译、路由、OpenAI/Gemini 适配（注入 fake client，离线）。"""
from types import SimpleNamespace

import pytest

from aichatgroup.domain.types import GatewayResponse, Usage
from aichatgroup.gateway import (
    ANTHROPIC_PREFIXES,
    GEMINI_PREFIXES,
    OPENAI_PREFIXES,
    GeminiGateway,
    OpenAIGateway,
    RouterGateway,
    build_gateway,
    parse_model_spec,
)
from aichatgroup.gateway._translate import (
    flatten_messages,
    flatten_system,
    join_user_text,
)

# Anthropic 形状的规范 prompt 样本（含 cache_control，翻译时应被剥掉）
SYSTEM = [
    {"type": "text", "text": "S1", "cache_control": {"type": "ephemeral"}},
    {"type": "text", "text": "S2"},
]
MESSAGES = [
    {"role": "user", "content": "H1"},
    {"role": "user", "content": [{"type": "text", "text": "tail", "cache_control": {"type": "ephemeral"}}]},
]


# ---- 翻译 --------------------------------------------------------------
def test_flatten_system_joins_blocks():
    assert flatten_system(SYSTEM) == "S1\n\nS2"


def test_flatten_messages_strips_cache_control():
    out = flatten_messages(MESSAGES)
    assert out == [{"role": "user", "content": "H1"}, {"role": "user", "content": "tail"}]
    assert all("cache_control" not in m["content"] for m in out)


def test_join_user_text():
    assert join_user_text(MESSAGES) == "H1\n\ntail"


# ---- 模型 spec 解析 ----------------------------------------------------
@pytest.mark.parametrize("spec,alias,model", [
    ("anthropic#claude-opus-4-8", "anthropic", "claude-opus-4-8"),
    ("openai#gpt-4o", "openai", "gpt-4o"),
    ("  Gemini # gemini-2.0-flash ", "gemini", "gemini-2.0-flash"),
    ("claude-opus-4-8", None, "claude-opus-4-8"),   # 裸名 → 无别名
])
def test_parse_model_spec(spec, alias, model):
    assert parse_model_spec(spec) == (alias, model)


# ---- Router ------------------------------------------------------------
class _Tag:
    def __init__(self, name):
        self.name = name
        self.seen_model = None

    def complete(self, system, messages, model_id, max_tokens=1024):
        self.seen_model = model_id
        return GatewayResponse(text=self.name, usage=Usage())


def _router():
    r = RouterGateway()
    r.register("anthropic", _Tag("anthropic"), ANTHROPIC_PREFIXES, default=True)
    r.register("openai", _Tag("openai"), OPENAI_PREFIXES)
    r.register("gemini", _Tag("gemini"), GEMINI_PREFIXES)
    return r


@pytest.mark.parametrize("spec,expected", [
    # 显式别名
    ("anthropic#claude-opus-4-8", "anthropic"),
    ("openai#gpt-4o", "openai"),
    ("gemini#gemini-2.0-flash", "gemini"),
    ("openai#claude-opus-4-8", "openai"),   # 别名压倒模型名：名叫 claude 也走 openai
    # 裸名 → 前缀推断（向后兼容）
    ("claude-opus-4-8", "anthropic"),
    ("gpt-4o", "openai"),
    ("o3-mini", "openai"),
    ("gemini-2.0-flash", "gemini"),
    ("some-unknown-model", "anthropic"),    # 落 default
])
def test_router_dispatch(spec, expected):
    assert _router().route(spec).name == expected


def test_router_strips_alias_before_delegating():
    tag = _Tag("openai")
    r = RouterGateway()
    r.register("anthropic", _Tag("anthropic"), ANTHROPIC_PREFIXES, default=True)
    r.register("openai", tag, OPENAI_PREFIXES)
    r.complete(SYSTEM, MESSAGES, "openai#gpt-4o")
    # 下游只应收到真实模型名，别名已剥掉
    assert tag.seen_model == "gpt-4o"


def test_router_complete_delegates():
    assert _router().complete(SYSTEM, MESSAGES, "openai#gpt-4o").text == "openai"


def test_router_unknown_alias_raises():
    with pytest.raises(KeyError):
        _router().route("nope#some-model")


def test_router_no_default_raises():
    with pytest.raises(KeyError):
        RouterGateway().route("whatever")


def test_router_alias_only_provider():
    # 额外命名别名不带前缀，只能通过 alias#model 寻址
    r = RouterGateway()
    r.register("deepseek", _Tag("deepseek"))
    assert r.route("deepseek#deepseek-chat").name == "deepseek"


# ---- OpenAI 适配 -------------------------------------------------------
class FakeOpenAIClient:
    def __init__(self):
        self.captured = None
        self.chat = self
        self.completions = self

    def create(self, model, max_tokens, messages):
        self.captured = {"model": model, "max_tokens": max_tokens, "messages": messages}
        usage = SimpleNamespace(
            prompt_tokens=100, completion_tokens=20,
            prompt_tokens_details=SimpleNamespace(cached_tokens=64),
        )
        choice = SimpleNamespace(message=SimpleNamespace(content="嗨，我是 GPT。"))
        return SimpleNamespace(choices=[choice], usage=usage)


def test_openai_gateway_translates_and_reads_usage():
    fake = FakeOpenAIClient()
    gw = OpenAIGateway(client=fake)
    resp = gw.complete(SYSTEM, MESSAGES, "gpt-4o", max_tokens=256)

    assert resp.text == "嗨，我是 GPT。"
    assert resp.usage.input_tokens == 100
    assert resp.usage.output_tokens == 20
    assert resp.usage.cache_read_input_tokens == 64
    # system 合成一条 + 历史/尾部各一条 user；无 cache_control
    assert fake.captured["messages"] == [
        {"role": "system", "content": "S1\n\nS2"},
        {"role": "user", "content": "H1"},
        {"role": "user", "content": "tail"},
    ]
    assert fake.captured["model"] == "gpt-4o"
    assert fake.captured["max_tokens"] == 256


# ---- Gemini 适配 -------------------------------------------------------
class FakeGeminiModels:
    def __init__(self):
        self.captured = None

    def generate_content(self, model, contents, config):
        self.captured = {"model": model, "contents": contents, "config": config}
        return SimpleNamespace(
            text="我是 Gemini。",
            usage_metadata=SimpleNamespace(
                prompt_token_count=80, candidates_token_count=15,
                cached_content_token_count=0,
            ),
        )


class FakeGeminiClient:
    def __init__(self):
        self.models = FakeGeminiModels()


def test_gemini_gateway_translates_and_reads_usage():
    fake = FakeGeminiClient()
    gw = GeminiGateway(client=fake)
    resp = gw.complete(SYSTEM, MESSAGES, "gemini-2.0-flash", max_tokens=128)

    assert resp.text == "我是 Gemini。"
    assert resp.usage.input_tokens == 80
    assert resp.usage.output_tokens == 15
    cap = fake.models.captured
    assert cap["model"] == "gemini-2.0-flash"
    assert cap["contents"] == "H1\n\ntail"          # 全部 user 文本拼成单轮
    assert cap["config"]["system_instruction"] == "S1\n\nS2"
    assert cap["config"]["max_output_tokens"] == 128


# ---- factory -----------------------------------------------------------
from aichatgroup.config import ProviderSpec  # noqa: E402


class _Settings:
    def __init__(self):
        self.anthropic_api_key = None
        self.openai_api_key = None
        self.openai_base_url = None
        self.openai_prefixes = ""
        self.gemini_api_key = None
        self.providers = []


def test_build_gateway_wires_anthropic_and_defaults():
    s = _Settings()
    s.anthropic_api_key = "k"  # anthropic 包在测试环境可用
    router = build_gateway(s)
    assert router.route("anthropic#claude-opus-4-8") is not None
    assert router.route("claude-opus-4-8") is not None   # 裸名前缀推断
    assert router.route("unknown") is not None           # default 落到 anthropic


def test_build_gateway_registers_extra_named_provider():
    s = _Settings()
    # 用 anthropic kind 装一个额外别名（openai/gemini 的 SDK 测试环境未装）
    s.providers = [ProviderSpec(alias="claude2", kind="anthropic", api_key="k")]
    router = build_gateway(s)
    assert "claude2" in router.aliases
    assert router.route("claude2#claude-opus-4-8") is not None


def test_build_gateway_no_keys_raises():
    with pytest.raises(RuntimeError):
        build_gateway(_Settings())


def test_build_gateway_extra_providers_arg():
    s = _Settings()
    s.anthropic_api_key = "k"
    extra = [ProviderSpec(alias="claude2", kind="anthropic", api_key="k")]
    router = build_gateway(s, extra_providers=extra)
    assert "claude2" in router.aliases


# ---- 声明式 provider 配置 ---------------------------------------------
def test_provider_spec_from_dict_maps_fields(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek")
    spec = ProviderSpec.from_dict({
        "alias": "deepseek",
        "type": "openai",
        "provider_url": "https://api.deepseek.com/v1",
        "api_key_env": "DEEPSEEK_API_KEY",
    })
    assert spec.alias == "deepseek"
    assert spec.kind == "openai"                        # type → kind
    assert spec.base_url == "https://api.deepseek.com/v1"  # provider_url → base_url
    assert spec.api_key == "sk-deepseek"                # api_key_env → 解析


def test_provider_spec_requires_alias():
    with pytest.raises(ValueError):
        ProviderSpec.from_dict({"type": "openai"})


def test_load_provider_specs_from_file(tmp_path):
    from aichatgroup.config import load_provider_specs
    p = tmp_path / "providers.json"
    p.write_text(
        '{"providers": ['
        '{"alias": "deepseek", "type": "openai", "provider_url": "u1"},'
        '{"alias": "g", "type": "gemini"}'
        ']}',
        encoding="utf-8",
    )
    specs = load_provider_specs(p)
    assert [s.alias for s in specs] == ["deepseek", "g"]
    assert specs[0].base_url == "u1"
    assert specs[1].kind == "gemini"
