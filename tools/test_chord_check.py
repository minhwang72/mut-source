"""코드 재판독으로 첫 판독을 맞추는가(tools/chord_check.fix_system)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from chord_check import ChordAt, fix_system, norm

SP = 10
GEO = {"spacing": SP, "staffTop": 100, "staffBottom": 140, "left": 0, "right": 400, "bars": [100, 200, 300]}


def chord(text, x):
    return {"text": text, "box": {"x": x, "y": 70, "w": 20, "h": 12}, "confidence": 0.9}


def ink_with(*xs):
    ink = np.zeros((200, 400), bool)
    for x in xs:
        ink[72:80, x:x + 18] = True
    return ink


def test_norm():
    assert norm("EM7") == norm("Emaj7") == norm("E△7") and norm("E7(sus4)") == norm("E7sus4")


def test_text_fixed_and_missing_added_at_ink():
    # camp0814b-04: 'Asus2' 는 가사 글자가 섞인 것 / set0802-1: 마디 2 의 D 를 놓쳤다
    ours = [chord("Asus2", 20), chord("G", 220)]
    theirs = [ChordAt(text="A", measure=1), ChordAt(text="D", measure=2), ChordAt(text="G", measure=3)]
    got = fix_system(ours, theirs, GEO, ink_with(20, 150, 220))
    assert [(c["text"], c["box"]["x"]) for c in got] == [("A", 20), ("D", 150), ("G", 220)]


def test_measure_numbers_not_trusted():
    # wish0906-2 단6: 두 번째 판독이 마디를 하나 더 셌다 — 그래도 앞뒤 사이 잉크로 넣는다
    ours = [chord("A", 20), chord("G", 220)]
    theirs = [ChordAt(text="A", measure=1), ChordAt(text="D", measure=3), ChordAt(text="G", measure=5)]
    got = fix_system(ours, theirs, GEO, ink_with(20, 150, 220))
    assert [c["text"] for c in got] == ["A", "D", "G"]


def test_refuse_when_place_or_root_disagrees():
    ours = [chord("A", 20), chord("G", 220)]
    # 근음까지 다르면 어느 쪽인지 모른다
    assert fix_system(ours, [ChordAt(text="Bm", measure=1), ChordAt(text="G", measure=3)],
                      GEO, ink_with(20, 220)) is None
    # 놓친 코드 자리에 잉크 덩어리가 없으면 넣지 않는다
    assert fix_system(ours, [ChordAt(text="A", measure=1), ChordAt(text="D", measure=2),
                             ChordAt(text="G", measure=3)], GEO, ink_with(20, 220)) is None
    # 첫 판독에만 있는 코드는 가를 수 없다
    assert fix_system(ours, [ChordAt(text="A", measure=1)], GEO, ink_with(20, 220)) is None


def test_align_strip_primary():
    from chord_check import align
    # t027-3: 첫 판독이 'E'·'♭/F' 로 쪼갬 / t059-7: 한 글자 코드 'E' 를 놓침
    geo = {**GEO, "headEnd": 10}
    ink = ink_with(20, 120, 145, 220)                       # F · E · ♭/F · F(상자 없음)
    ink[77:80, 300:303] = True                              # 점 하나 — 잡티
    ours = [chord("F", 20), chord("E", 120), chord("Bb/F", 145)]
    got = align(ours, [ChordAt(text="F", measure=1), ChordAt(text="Eb/F", measure=2),
                       ChordAt(text="F", measure=3)], geo, ink, (30, 18), cw=14, ch=8)
    assert [(c["text"], c["box"]["x"], c["box"]["w"]) for c in got] == \
        [("F", 20, 20), ("Eb/F", 120, 45), ("F", 220, 18)]
    # 첫 판독 상자의 근음이 다르면 짝짓지 않는다
    assert align([chord("B", 20)], [ChordAt(text="A", measure=1)], geo, ink_with(20), (30, 18),
                 cw=14, ch=8) is None


if __name__ == "__main__":
    test_norm(); test_text_fixed_and_missing_added_at_ink(); test_measure_numbers_not_trusted()
    test_refuse_when_place_or_root_disagrees(); test_align_strip_primary()
    print("ok")



# ── 두 판독이 갈린 마디만 짚는다(마디 번호는 믿지 않고 일치한 코드 사이로) ──
from types import SimpleNamespace as _NS
import chord_check as _CC
_g = {"left": 0, "right": 400, "bars": [100, 200, 300], "spacing": 10}
_sd = {"measures": 4, "notes": []}
_c = lambda t, x: {"text": t, "box": {"x": x - 5, "y": 0, "w": 10, "h": 10}}
_ours = [_c("C", 50), _c("F", 150), _c("G", 250), _c("C", 350)]
# 마디3 코드만 다르다 → 앞뒤로 일치한 코드(마디2·마디4) 사이 = 2~4
assert _CC._disagree(_ours, [_NS(text=t) for t in ["C", "F", "Am", "C"]], _g, _sd) == [2, 3, 4]
# 두 번째 판독만 읽은 코드가 끝에 있다 → 마지막 일치(마디4)부터 끝까지
assert _CC._disagree(_ours, [_NS(text=t) for t in ["C", "F", "G", "C", "G"]], _g, _sd) == [4]
_st = [{"system": 0, "measures": 4}]
_CC._review(_st, 0, [3])
assert _st[0]["review"] == [f"마디 3: {_CC.REVIEW}"]
_CC._review(_st, 0, None)
assert _CC.REVIEW in _st[0]["review"]
print("ok disagree")
