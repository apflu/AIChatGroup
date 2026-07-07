from aichatgroup.domain import PacingConfig
from aichatgroup.engine import infer_pause, resolve_pauses


def test_first_pause_always_zero():
    cfg = PacingConfig()
    pauses = resolve_pauses(["a", "b"], [None, None], cfg)
    assert pauses[0] == 0.0
    assert len(pauses) == 2


def test_inferred_pause_scales_with_length():
    cfg = PacingConfig(base_pause_s=0.4, per_char_s=0.05, min_pause_s=0.3, max_pause_s=6.0)
    short = infer_pause("嗨", cfg)
    long = infer_pause("这是一句相当长的台词" * 3, cfg)
    assert long > short
    assert short >= cfg.min_pause_s
    assert long <= cfg.max_pause_s


def test_inferred_pause_clamped_to_max():
    cfg = PacingConfig(base_pause_s=0.4, per_char_s=1.0, max_pause_s=2.0)
    assert infer_pause("很长很长很长很长", cfg) == 2.0


def test_explicit_hint_overrides_inference():
    cfg = PacingConfig(per_char_s=0.05)
    pauses = resolve_pauses(["a", "b"], [None, 3.0], cfg)
    assert pauses[1] == 3.0


def test_explicit_scale_reflects_personality():
    hasty = PacingConfig(explicit_scale=0.5)   # 急性子，把停顿减半
    patient = PacingConfig(explicit_scale=2.0)  # 慢性子，把停顿加倍
    assert resolve_pauses(["a", "b"], [None, 2.0], hasty)[1] == 1.0
    assert resolve_pauses(["a", "b"], [None, 2.0], patient)[1] == 4.0


def test_explicit_hint_clamped_to_max():
    cfg = PacingConfig(max_pause_s=3.0)
    assert resolve_pauses(["a", "b"], [None, 99.0], cfg)[1] == 3.0
