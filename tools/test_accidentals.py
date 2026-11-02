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
    # set0802-3 단9 x1852: A4·F4 사이에 걸친 상자(0.63)보다 칸에 맞는 F4(0.36)가 기준
    st9 = cv.Staff(0, 3494, 3567, [3494, 3513, 3531, 3549, 3567], [(y, y) for y in (3494, 3513, 3531, 3549, 3567)], 0, 2500)
    g = {"x": 1840, "y": 3534, "w": 24, "h": 22, "conf": 0.63}
    h = {"x": 1840, "y": 3548, "w": 24, "h": 16, "conf": 0.36}
    assert split_stacked([g, h], 18.25, st9) == 1
    assert staff_pos(g, st9) == "A4" and staff_pos(h, st9) == "F4"


if __name__ == "__main__":
    test_links_flat_and_natural(); test_courtesy_key_at_end_is_ignored()
    test_mid_system_key_cluster_blocks(); test_staff_pos(); test_split_stacked_third()
    print("ok")


def test_chord_member_follows_its_base():
    from detstruct import order_chords
    def n(x, chord=False, m=1):
        return {"measure": m, "chord": chord, "rest": False, "duration": "quarter",
                "head": {"x": x, "y": 0, "w": 10, "h": 8}}
    a, b, c = n(100, chord=True), n(102), n(150)
    assert order_chords([a, b, c]) == [b, a, c]          # 구성음이 앞에 왔다 → 뒤로
    d, e, f = n(100), n(101, chord=True), n(150)
    assert order_chords([d, e, f]) == [d, e, f]          # 이미 바르면 그대로
    # camp0814b-06 단9: 구성음 둘이 바탕음 앞에 — 둘 다 그 뒤로
    p, q, r, t = n(100), n(101, chord=True), n(160, chord=True), n(161, chord=True)
    u = n(162)
    assert order_chords([p, q, r, t, u]) == [p, q, u, r, t]
    # 구성음은 바탕음 음가를 따른다
    v, w = dict(n(300), duration="half"), dict(n(301, chord=True), duration="quarter")
    assert order_chords([v, w])[1]["duration"] == "half"


if __name__ == "__main__":
    test_chord_member_follows_its_base(); print("ok chord")


def test_tie_across_systems():
    from detstruct import _tie_out, _ties_across_systems
    # day2conti-4: 단 끝 D4 에서 오른쪽으로 나가는 약한 곡선 + 다음 단 첫 D4 → 붙임줄
    a = {"x": 1900, "y": 795, "w": 20, "h": 14}
    _tie_out([{"x": 1800, "y": 795, "w": 20, "h": 14}, a],
             [{"x": 1915, "y": 805, "w": 40, "h": 10, "conf": 0.17}], 18)
    assert a["tie_out"]
    b = {"x": 1500, "y": 795, "w": 20, "h": 14}
    _tie_out([b], [{"x": 1400, "y": 805, "w": 40, "h": 10, "conf": 0.2}], 18)   # 왼쪽 곡선 — 아니다
    assert not b["tie_out"]
    n = lambda pos, **k: {"pos": pos, "rest": False, "chord": False, **k}
    sys_ = [{"notes": [n("C4"), n("D4", tieOut=True)]}, {"notes": [n("D4"), n("E4")]},
            {"notes": [n("F4", tieOut=True)]}, {"notes": [n("G4")]}]
    assert _ties_across_systems(sys_) == 1
    assert sys_[0]["notes"][1]["tie"] and not sys_[2]["notes"][0].get("tie")   # 다른 음이면 안 잇는다


if __name__ == "__main__":
    test_tie_across_systems(); print("ok tie-across")
