"""곡선 상자는 **그 상자 안쪽** 자리만 반증한다."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from durations import _on_curve                                # noqa: E402

SP = 18.0
HEAD = {"x": 700.0, "y": 1290.0, "w": 25.0, "h": 20.0}
# 머리보다 왼쪽에서 시작해 x 를 덮는 긴 이음줄 — 단, 한참 아래에 있다
FAR = [{"x": 380.0, "y": 1475.0, "w": 443.0, "h": 46.0}]
NEAR = [{"x": 380.0, "y": 1296.0, "w": 443.0, "h": 46.0}]


def test_curve_far_below_is_not_evidence():
    # 실측 camp0814c-04 단3 마디2 — 이음줄은 y 1475, 붙임점 자리는 y 1309
    assert _on_curve(718, 1309, FAR, SP, HEAD) is False


def test_curve_top_at_the_dot_still_vetoes():
    # 원래 막으려던 경우: 아치 꼭대기가 붙임점 자리에 정확히 온다
    assert _on_curve(718, 1300, NEAR, SP, HEAD) is True


def test_curve_starting_at_this_head_is_not_evidence():
    own = [{"x": 710.0, "y": 1296.0, "w": 400.0, "h": 46.0}]
    assert _on_curve(718, 1300, own, SP, HEAD) is False


if __name__ == "__main__":
    test_curve_far_below_is_not_evidence()
    test_curve_top_at_the_dot_still_vetoes()
    test_curve_starting_at_this_head_is_not_evidence()
    print("ok")
