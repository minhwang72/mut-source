"""
모자란 마디에서만 속 빈 머리를 한 단계 올린다.

통째로 되돌리는 것은 전에 재서 버렸다(103장 깨진 마디 804 → 826).
`promote_dots` 와 같은 틀로 가두면 맞는 마디는 후보조차 안 된다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from durations import hollow_score                             # noqa: E402
from fitdur import promote_hollow                              # noqa: E402


def note(d, hollow=0.0, dotted=False):
    return {"duration": d, "dotted": dotted, "hollow": hollow}


def measure(notes, rest=0.0):
    return {"notes": notes, "rest": rest, "items": list(notes)}


def test_promotes_the_hollow_head_that_fills_the_measure():
    # ♩ ♩ ♩ = 3박. 속이 빈 셋째를 2분음표로 올리면 정확히 4박
    ms = [measure([note("quarter"), note("quarter"), note("quarter", 0.36)]),
          measure([note("whole")])]
    assert promote_hollow([ms]) == 1
    assert ms[0]["notes"][2]["duration"] == "half"
    assert ms[0]["notes"][2]["hollowPromoted"] is True


def test_leaves_filled_heads_alone():
    ms = [measure([note("quarter"), note("quarter"), note("quarter", 0.02)]),
          measure([note("whole")])]
    assert promote_hollow([ms]) == 0


def test_never_touches_a_measure_that_already_fits():
    ms = [measure([note("quarter", 0.9), note("quarter", 0.9),
                   note("half", 0.9)]),
          measure([note("whole")])]
    assert promote_hollow([ms]) == 0


def test_only_half_and_whole_steps_use_hollowness():
    """속 비움은 2분·온음표만 가른다 — 8분→4분은 증거가 아니다."""
    from fitdur import UP, DOWN
    assert set(UP) == {"quarter", "half"}
    assert set(DOWN) == {"half", "whole"}


def test_demotes_a_filled_head_read_as_half():
    from fitdur import demote_hollow
    # ♩ ♩ 𝅗𝅥 = 4박인데 2분음표 머리가 꽉 찼다 → 4분음표로 내리면 3박.
    # 넘치는 마디가 아니므로 손대지 않는다.
    ms = [measure([note("quarter"), note("quarter"), note("half", 0.0)]),
          measure([note("whole")])]
    assert demote_hollow([ms]) == 0
    # ♩ ♩ ♩ 𝅗𝅥 = 5박 → 꽉 찬 2분음표를 4분으로 내리면 정확히 4박
    ms2 = [measure([note("quarter"), note("quarter"), note("quarter"),
                    note("half", 0.0)]),
           measure([note("whole")])]
    assert demote_hollow([ms2]) == 1
    assert ms2[0]["notes"][3]["duration"] == "quarter"


def test_does_not_demote_a_really_hollow_head():
    from fitdur import demote_hollow
    ms = [measure([note("quarter"), note("quarter"), note("quarter"),
                   note("half", 0.7)]),
          measure([note("whole")])]
    assert demote_hollow([ms]) == 0


def test_dotted_note_steps_by_its_dotted_value():
    # ♩. ♩. = 3박 → 점4분 하나를 점2분으로 올리면 1.5박이 늘어 4.5박.
    # 정확히 안 맞으므로 손대지 않는다.
    ms = [measure([note("quarter", 0.5, True), note("quarter", 0.5, True)]),
          measure([note("whole")])]
    assert promote_hollow([ms]) == 0


def test_hollow_score_splits_filled_and_hollow():
    import numpy as np
    box = {"x": 10, "y": 10, "w": 20, "h": 16}
    filled = np.zeros((40, 40), dtype="float32")
    filled[10:27, 10:31] = 0.0            # 통째로 검정
    filled[:, :] = 255.0
    filled[10:27, 10:31] = 20.0
    hollow = filled.copy()
    hollow[14:23, 14:27] = 245.0          # 가운데만 종이
    assert hollow_score(box, filled) < 0.1
    assert hollow_score(box, hollow) > 0.8


def test_x_head_is_not_hollow():
    """× 머리(리듬 슬래시)는 가운데가 비어도 속 빈 머리가 아니다."""
    import numpy as np
    from durations import hollow_score
    box = {"x": 10, "y": 10, "w": 24, "h": 20}
    g = np.full((60, 60), 255.0, dtype="float32")
    # × — 대각선만 잉크. 테두리 좌우 가운데는 비어 있다.
    for t in range(20):
        g[10 + t, 10 + int(t * 24 / 20)] = 20.0
        g[10 + t, 33 - int(t * 24 / 20)] = 20.0
    # 잴 수 없음(None) — 0 이면 "꽉 찼다"는 증거로 쓰여 2분음표가 깎인다
    assert hollow_score(box, g) is None

    # 속 빈 머리 — 테두리가 이어져 있고 가운데만 종이
    h = np.full((60, 60), 255.0, dtype="float32")
    h[10:31, 10:35] = 20.0
    h[14:27, 14:31] = 245.0
    assert hollow_score(box, h) > 0.5


if __name__ == "__main__":
    test_promotes_the_hollow_head_that_fills_the_measure()
    test_leaves_filled_heads_alone()
    test_never_touches_a_measure_that_already_fits()
    test_only_half_and_whole_steps_use_hollowness()
    test_demotes_a_filled_head_read_as_half()
    test_does_not_demote_a_really_hollow_head()
    test_dotted_note_steps_by_its_dotted_value()
    test_hollow_score_splits_filled_and_hollow()
    test_x_head_is_not_hollow()
    print("ok")


