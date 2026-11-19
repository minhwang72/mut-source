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


def test_merged_chord_flagged():
    # t049-6: "D(add2)A" — 조옮김하면 뒤 A 가 남는다. 고치지 않고 그 마디만 확인 필요로
    from chord_check import flag_merged
    systems = [{"index": 0, "chords": [chord("A/C#", 120), chord("D(add2)A", 160), chord("D", 220)]}]
    st = [{"system": 0, "measures": 4, "notes": []}]
    assert flag_merged(systems, st, [dict(GEO, index=0)]) == 1
    assert [r.split(":")[0] for r in st[0]["review"]] == ["마디 2"]
    st2 = [{"system": 0, "measures": 4, "notes": []}]
    ok = [{"index": 0, "chords": [chord("D(add2)", 160), chord("C7(b9)", 220), chord("Am7/G", 300)]}]
    assert flag_merged(ok, st2, [dict(GEO, index=0)]) == 0 and "review" not in st2[0]


def test_doubt_marks_only_differing_chords():
    # 코드만 바꾸기는 코드를 짚는다 — 다른 것만, 놓친 코드는 앞뒤를
    from chord_check import _doubt_diff
    ours = [chord("C", 10), chord("Am", 60), chord("F", 110), chord("G", 160)]
    _doubt_diff(ours, [ChordAt(text=t, measure=1) for t in ["C", "Am7", "F", "G"]])
    assert [bool(c.get("doubt")) for c in ours] == [False, True, False, False]
    ours = [chord("C", 10), chord("F", 110), chord("G", 160)]
    _doubt_diff(ours, [ChordAt(text=t, measure=1) for t in ["C", "Am", "F", "G"]])
    assert [bool(c.get("doubt")) for c in ours] == [True, True, False]


def test_leftover_chord_ink_becomes_doubt():
    # t017-1 단2: 두 번째 판독이 본 'Cm7' 을 자리 못 잡아 옛 키 글자로 남았다
    from chord_check import leftovers
    chords = [chord("F7", 150), chord("Bb", 300)]
    ink = ink_with(150, 300)
    ink[72:80, 20:38] = True                           # 상자 밖, 코드 글자 높이의 잉크
    ink[76:82, 60:64] = True                           # 마디 번호처럼 작은 글자 — 코드 아님
    systems = [{"index": 0, "chords": chords}]
    assert leftovers(systems, [dict(GEO, index=0)], ink, {0: ["Cm7", "F7", "Bb"]})["added"] == 1
    got = systems[0]["chords"][0]
    assert got["text"] == "Cm7" and got["doubt"] and got["missing"] and got["box"]["x"] == 20
    # 앞에 마디 번호 같은 좁은 잉크가 먼저 있어도 폭이 맞는 쪽에 준다
    ink2 = ink.copy(); ink2[72:80, 4:9] = True        # "9" 같은 한 글자
    systems = [{"index": 0, "chords": [chord("F7", 150), chord("Bb", 300)]}]
    leftovers(systems, [dict(GEO, index=0)], ink2, {0: ["Cm7", "F7", "Bb"]})
    assert [c["box"]["x"] for c in systems[0]["chords"] if c.get("missing")] == [20]
    # 두 번째 판독이 그 자리에 코드를 안 봤으면(마디 번호·기호) 세우지 않는다
    systems = [{"index": 0, "chords": [chord("F7", 150), chord("Bb", 300)]}]
    assert leftovers(systems, [dict(GEO, index=0)], ink, {0: ["F7", "Bb"]})["added"] == 0
    # 코드를 하나도 못 읽은 단은 다른 단의 코드 띠를 빌려 세운다(t030-2 단4·5)
    systems = [{"index": 0, "chords": [dict(chord("F7", 150), box={"x": 150, "y": 270, "w": 20, "h": 12}),
                                       dict(chord("Bb", 300), box={"x": 300, "y": 270, "w": 20, "h": 12})]}]
    ink4 = np.zeros((800, 400), bool)
    ink4[270:282, 150:170] = True; ink4[270:282, 300:320] = True
    ink4[570:582, 50:60] = True; ink4[570:582, 200:210] = True
    geo2 = [dict(GEO, index=0, staffTop=300, staffBottom=340), dict(GEO, index=1, staffTop=600, staffBottom=640)]
    r = leftovers(systems, geo2, ink4, {0: ["F7", "Bb"], 1: ["A", "B"]})
    assert r["added"] == 2 and not r["unplaced"], r
    assert [(c["text"], c["box"]["x"]) for c in systems[1]["chords"]] == [("A", 50), ("B", 200)]
    # 자리를 못 잡은 코드는 세어 돌려준다
    r = leftovers([{"index": 0, "chords": [chord("F7", 150)]}], [dict(GEO, index=0)], ink_with(150), {0: ["F7", "G"]})
    assert r["unplaced"] == {0: 1}, r
    # 다 덮여 있으면 아무것도 안 세운다
    systems = [{"index": 0, "chords": [chord("F7", 150), chord("Bb", 300)]}]
    assert leftovers(systems, [dict(GEO, index=0)], ink_with(150, 300), {0: ["F7", "Bb"]})["added"] == 0


if __name__ == "__main__":
    test_norm(); test_text_fixed_and_missing_added_at_ink(); test_measure_numbers_not_trusted()
    test_refuse_when_place_or_root_disagrees(); test_align_strip_primary()
    test_merged_chord_flagged()
    test_doubt_marks_only_differing_chords()
    test_leftover_chord_ink_becomes_doubt()
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
