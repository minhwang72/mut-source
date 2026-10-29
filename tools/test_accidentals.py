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


def test_split_stacked_third():
    from detstruct import split_stacked
    # 실측 set0802-3 단0 x1218: A4(784, 0.82) 아래 F4 상자가 796 으로 쏠려 G4 로 읽혔다
    st = cv.Staff(0, 739, 812, [739, 757, 774, 793, 812], [(y, y) for y in (739, 757, 774, 793, 812)], 0, 2500)
    a = {"x": 1220, "y": 774, "w": 23, "h": 20, "conf": 0.82}
    b = {"x": 1219, "y": 784.5, "w": 24, "h": 23, "conf": 0.63}
    assert staff_pos(b, st) == "G4"
    assert split_stacked([b, a], 18.25) == 1
    assert staff_pos(a, st) == "A4" and staff_pos(b, st) == "F4"
    # 기둥 양옆으로 엇갈린 진짜 2도, 이미 한 칸 떨어진 3도는 그대로
    c = {"x": 1300, "y": 774, "w": 23, "h": 20, "conf": 0.9}
    d = {"x": 1324, "y": 783, "w": 23, "h": 20, "conf": 0.5}
    e = {"x": 1400, "y": 774, "w": 23, "h": 20, "conf": 0.9}
    f = {"x": 1400, "y": 792.5, "w": 23, "h": 20, "conf": 0.5}
    assert split_stacked([c, d, e, f], 18.25) == 0


if __name__ == "__main__":
    test_links_flat_and_natural(); test_courtesy_key_at_end_is_ignored()
    test_mid_system_key_cluster_blocks(); test_staff_pos(); test_split_stacked_third()
    print("ok")


def test_chord_member_follows_its_base():
    from detstruct import order_chords
    def n(x, chord=False, m=1):
        return {"measure": m, "chord": chord, "rest": False,
                "head": {"x": x, "y": 0, "w": 10, "h": 8}}
    a, b, c = n(100, chord=True), n(102), n(150)
    assert order_chords([a, b, c]) == [b, a, c]          # 구성음이 앞에 왔다 → 뒤로
    d, e, f = n(100), n(101, chord=True), n(150)
    assert order_chords([d, e, f]) == [d, e, f]          # 이미 바르면 그대로


if __name__ == "__main__":
    test_chord_member_follows_its_base(); print("ok chord")
