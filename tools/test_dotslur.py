"""긴 이음줄 상자 아래의 붙임점도 센다 — durations._occupancy 가 곡선 상자를 가리지 않는다."""
import sys
sys.path.insert(0, "tools")
import numpy as np
from durations import read_durations, DOT_SCORE

SP = 18.0


def page(with_tie_box):
    g = np.full((200, 300), 255.0, dtype="float32")
    g[90:106, 60:82] = 20.0                       # 꽉 찬 머리
    yy, xx = np.ogrid[:200, :300]
    g[(xx - 95) ** 2 + (yy - 92) ** 2 <= 9] = 20.0  # 오른쪽 위 붙임점
    boxes = [{"class": "notehead_filled", "x": 60, "y": 90, "w": 22, "h": 16}]
    if with_tie_box:                              # 머리 위를 덮는 긴 이음줄 상자
        boxes.append({"class": "tie", "x": 70, "y": 70, "w": 200, "h": 40})
    return boxes, g


def test_dot_under_long_slur_box_counts():
    plain = read_durations(*page(False)[:1], SP, gray=page(False)[1])[0]
    under = read_durations(*page(True)[:1], SP, gray=page(True)[1])[0]
    assert plain["dotScore"] >= DOT_SCORE, plain["dotScore"]
    assert under["dotScore"] == plain["dotScore"], (under["dotScore"], plain["dotScore"])


if __name__ == "__main__":
    test_dot_under_long_slur_box_counts()
    print("ok")
