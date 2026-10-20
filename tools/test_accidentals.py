"""
임시표를 바로 오른쪽 머리에 붙이는가.

왜: 붙이지 못해 임시표 있는 단은 전부 막혔다(105장 중 4장은 그것만으로).
붙인 결과는 crosscheck 가 homr 음높이와 다시 대조한다.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from detstruct import link_accidentals, staff_pos
import sheetcv as cv

SP = 10


def head(x, y):
    return {"rest": False, "head": {"x": x, "y": y - 4, "w": 12, "h": 8}}


def acc(cls, x, cy):
    h = 30 if cls == "accidental_flat" else 26
    y = cy + SP * 0.5 - h if cls == "accidental_flat" else cy - h / 2
    return {"class": cls, "x": x, "y": y, "w": 8, "h": h}


def test_links_flat_and_natural():
    notes = [head(100, 50), head(140, 45), head(180, 50)]
    ok = link_accidentals([acc("accidental_flat", 128, 45),
                           acc("accidental_natural", 168, 50)], notes, SP)
    assert ok and notes[1]["accidental"] == -1 and notes[2].get("natural")
    assert "accidental" not in notes[0]


def test_courtesy_key_at_end_is_ignored():
    notes = [head(100, 50)]
    assert link_accidentals([acc("accidental_flat", 300, 40),
                             acc("accidental_flat", 310, 55)], notes, SP)
    assert "accidental" not in notes[0]


def test_mid_system_key_cluster_blocks():
    notes = [head(100, 50), head(200, 50)]
    assert not link_accidentals([acc("accidental_sharp", 170, 40),
                                 acc("accidental_sharp", 178, 55)], notes, SP)


def test_staff_pos():
    st = cv.Staff(0, 100, 140, [100, 110, 120, 130, 140], [(y, y) for y in range(100, 141, 10)], 0, 500)
    assert staff_pos({"x": 0, "y": 136, "h": 8}, st) == "E4"      # 맨 아래 줄
    assert staff_pos({"x": 0, "y": 96, "h": 8}, st) == "F5"       # 맨 위 줄
    assert staff_pos({"x": 0, "y": 141, "h": 8}, st) == "D4"      # 아래 칸


if __name__ == "__main__":
    test_links_flat_and_natural(); test_courtesy_key_at_end_is_ignored()
    test_mid_system_key_cluster_blocks(); test_staff_pos()
    print("ok")
