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


def test_refuse_when_measure_or_place_disagrees():
    ours = [chord("A", 20), chord("G", 220)]
    # 함께 읽은 G 의 마디가 다르면 못 믿는다
    assert fix_system(ours, [ChordAt(text="A", measure=1), ChordAt(text="G", measure=2)],
                      GEO, ink_with(20, 220)) is None
    # 놓친 코드 자리에 잉크 덩어리가 없으면 넣지 않는다
    assert fix_system(ours, [ChordAt(text="A", measure=1), ChordAt(text="D", measure=2),
                             ChordAt(text="G", measure=3)], GEO, ink_with(20, 220)) is None
    # 첫 판독에만 있는 코드는 가를 수 없다
    assert fix_system(ours, [ChordAt(text="A", measure=1)], GEO, ink_with(20, 220)) is None


if __name__ == "__main__":
    test_norm(); test_text_fixed_and_missing_added_at_ink(); test_refuse_when_measure_or_place_disagrees()
    print("ok")
