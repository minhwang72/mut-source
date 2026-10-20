"""
쉼표에도 붙임점이 붙는다 — 오선을 지운 그림에서 **점 모양**만 센다.

실측 근거(set0802-1 단0 마디4): 𝄼. + 𝄾 + ♪ = 4박인데 쉼표에 점 판정이
없어서 𝄼 로 읽혔고, 그 마디가 1박 모자란 채 fit_page 로 갔다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np                                            # noqa: E402
from durations import rest_dot_score                          # noqa: E402
from fitdur import promote_dots                               # noqa: E402

SP = 18.0


def blank():
    return np.zeros((200, 200), dtype=bool)


REST = {"x": 60.0, "y": 92.0, "w": 18.0, "h": 9.0}


def test_finds_a_dot_right_above_the_rest():
    ns = blank()
    # 점은 쉼표 오른쪽 0.8칸, 위로 0.7칸 — 지름 0.4칸쯤인 작은 점
    cx, cy = int(REST["x"] + REST["w"] + SP * 0.8), int(96 - SP * 0.7)
    ns[cy - 3:cy + 4, cx - 3:cx + 4] = True
    assert rest_dot_score(ns, REST, SP) > 0


def test_blank_scores_zero():
    assert rest_dot_score(blank(), REST, SP) == 0.0


def test_a_barline_is_not_a_dot():
    ns = blank()
    cx = int(REST["x"] + REST["w"] + SP * 0.8)
    ns[:, cx - 1:cx + 2] = True        # 세로로 길게 — 막대선
    assert rest_dot_score(ns, REST, SP) == 0.0


def test_a_beam_is_not_a_dot():
    ns = blank()
    cy = int(96 - SP * 0.7)
    ns[cy - 1:cy + 2, :] = True        # 가로로 길게 — 빔
    assert rest_dot_score(ns, REST, SP) == 0.0


def test_beats_promote_a_dotted_rest():
    # 𝄼 + 𝄾 + ♪ = 3박 → 2분쉼표에 점을 붙이면 정확히 4박
    rest_h = {"duration": "half", "dotted": False, "rest": True,
              "dotScore": 0.22}
    rest_e = {"duration": "eighth", "dotted": False, "rest": True,
              "dotScore": 0.0}
    note = {"duration": "eighth", "dotted": False, "dotScore": 0.0}
    m = {"notes": [note], "rest": 2.5, "items": [rest_h, rest_e, note]}
    ms = [m, {"notes": [{"duration": "whole", "dotted": False}],
              "rest": 0.0, "items": []}]
    assert promote_dots([ms]) == 1
    assert rest_h["dotted"] is True
    assert m["rest"] == 3.5            # 쉼표 합을 다시 셌다


if __name__ == "__main__":
    test_finds_a_dot_right_above_the_rest()
    test_blank_scores_zero()
    test_a_barline_is_not_a_dot()
    test_a_beam_is_not_a_dot()
    test_beats_promote_a_dotted_rest()
    print("ok")
