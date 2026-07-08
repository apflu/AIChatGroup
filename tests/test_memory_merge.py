"""merge_memory：单条格式契约不变 + M2 追加去重。"""
from aichatgroup.message.generator import merge_memory


def test_single_delta_is_one_json_line():
    # 与 M1 逐字节一致的格式契约（test_store 也依赖）：空快照 + 单增量 = 紧凑单行
    assert merge_memory("", {"k": 1}) == '{"k": 1}'


def test_appends_new_fact_on_new_line():
    out = merge_memory('{"k": 1}', {"k": 2})
    assert out.split("\n") == ['{"k": 1}', '{"k": 2}']


def test_dedupes_identical_repeated_fact():
    # 反复出现的同一事实不该无限堆叠
    first = merge_memory("", {"mood": "兴奋"})
    again = merge_memory(first, {"mood": "兴奋"})
    assert again == first
    assert again.count("兴奋") == 1
