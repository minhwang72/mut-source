"""두 판독기 교차 검증 — tools/crosscheck.merge."""
import sys
sys.path.insert(0, "tools")
from crosscheck import merge


def n(d, m=1, dotted=False, rest=False, chord=False, guessed=False, head=True):
    x = {"duration": d, "dotted": dotted, "rest": rest, "chord": chord,
         "measure": m, "guessed": guessed, "beamGroup": -1}
    if head and not rest:
        x["head"] = {"x": 0, "y": 0, "w": 1, "h": 1}
    return x


def st(notes):
    return {"beats": 4.0, "systems": [{"notes": notes}]}


def test_agreement_clears_guess():
    s = st([n("half", guessed=True), n("half")])
    r = merge(s, [[["2", "2"]]])
    assert r["agree"] == 1 and not any(x["guessed"] for x in s["systems"][0]["notes"])


def test_homr_fixes_missing_rest_keeping_our_heads():
    # set0816-1: 원본 r4 4 4. 8 — 우리는 4분쉼표를 놓쳐 3박
    a, b, c = n("quarter"), n("quarter", dotted=True), n("eighth")
    s = st([a, b, c])
    r = merge(s, [[["r1", "1", "1.5", "0.5"]]])
    out = s["systems"][0]["notes"]
    assert r["homr"] == 1
    assert [x.get("rest") for x in out] == [True, False, False, False]
    assert out[1] is a and out[1]["duration"] == "quarter"


def test_chord_members_follow():
    lead, mem = n("quarter"), n("quarter", chord=True)
    s = st([lead, mem, n("quarter"), n("quarter")])   # 3박
    merge(s, [[["2", "1", "1"]]])
    assert lead["duration"] == mem["duration"] == "half"


def test_both_valid_but_different_blocks():
    s = st([n("eighth")] * 0 + [n("eighth") for _ in range(8)])
    r = merge(s, [[["0.75", "0.25", "0.5", "0.5", "0.75", "0.25", "0.5", "0.5"]]])
    assert r["conflict"] == 1 and s["systems"][0]["review"]


def test_seen_head_beats_homr_rest():
    # camp0814a-3: homr 가 첫 음(점8분)을 같은 길이 쉼표로 읽었다
    s = st([n("eighth", dotted=True), n("16th"), n("eighth"), n("eighth"),
            n("quarter"), n("eighth", rest=True), n("eighth")])
    r = merge(s, [[["r0.75", "0.25", "0.5", "0.5", "1", "r0.5", "0.5"]]])
    assert r["conflict"] == 0 and "review" not in s["systems"][0]


def test_extra_homr_measure_is_aligned_past():
    # homr 가 마디를 하나 더 찾아도 맞는 마디끼리 짝짓는다
    s = st([n("whole")])
    r = merge(s, [[["4"], ["4"]]])
    assert r["agree"] == 1


def test_system_count_differs_still_aligns():
    # 우리 2단 · homr 1단(단 나눔을 못 봄) — 마디 순서로 맞춘다
    s = {"beats": 4.0, "systems": [{"notes": [n("whole", guessed=True)]},
                                   {"notes": [n("half"), n("half")]}]}
    r = merge(s, [[["4"], ["2", "2"]]])
    assert r["agree"] == 2 and not s["systems"][0]["notes"][0]["guessed"]


def test_missed_barline_counts_as_agreement():
    # homr 가 세로줄 하나를 놓쳐 두 마디를 한 마디로 읽었다
    s = st([n("whole", m=1), n("half", m=2), n("half", m=2)])
    r = merge(s, [[["4", "2", "2"]]])
    assert r["conflict"] == 0 and r["homr"] == 0


def test_dissimilar_measures_are_not_paired():
    # 내용이 전혀 다른 마디가 위치로도 고정되지 않으면 homr 음가를 입히지 않는다
    s = st([n("whole", m=1)] + [n("eighth", m=2) for _ in range(4)] + [n("whole", m=3)])
    r = merge(s, [[["4"], ["1", "1", "1", "1"], ["2", "2"], ["4"]]])
    assert r["homr"] == 0


def test_anchored_dissimilar_measure_is_paired():
    # day2sb-1 단7: 앞뒤 마디가 짝지어진 자리 — 많이 달라도 같은 마디다
    s = st([n("whole", m=1), n("half", m=2, rest=True), n("eighth", m=2, rest=True),
            n("quarter", m=2), n("whole", m=3)])
    r = merge(s, [[["4"], ["r3", "r0.5", "0.5"], ["4"]]])
    assert r["homr"] == 1


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
    print("ok")


def test_stale_count_review_dropped_after_fix():
    s = st([n("quarter"), n("quarter", dotted=True), n("eighth")])
    s["systems"][0]["review"] = ["기존 개수 판독 4개와 검출 3개 불일치"]
    merge(s, [[["r1", "1", "1.5", "0.5"]]])
    assert "review" not in s["systems"][0]


if __name__ == "__main__":
    test_stale_count_review_dropped_after_fix()
    print("ok stale")


def test_homr_resolves_our_guess():
    # 우리가 8분 둘 중 하나를 4분으로 찍었다(guessed) — homr 는 다른 쪽을 골랐다
    a, b = n("quarter", guessed=True), n("eighth")
    c, d = n("eighth", guessed=True), n("half")
    s = st([a, b, c, d])                     # 1 + .5 + .5 + 2 = 4
    r = merge(s, [[["0.5", "0.5", "1", "2"]]])
    assert r.get("resolved") == 1
    assert [x["duration"] for x in (a, b, c, d)] == ["eighth", "eighth", "quarter", "half"]
    assert not any(x["guessed"] for x in (a, b, c, d))


def test_disagreement_on_unguessed_note_still_blocks():
    a, b = n("quarter", guessed=True), n("quarter")
    c, d = n("half"), n("whole", rest=False)
    s = st([n("half"), n("half")])
    s["systems"][0]["notes"][0]["guessed"] = True
    r = merge(s, [[["1", "1", "2"]]])        # 개수부터 다르다 — 고르기가 아니다
    assert r.get("resolved") is None


if __name__ == "__main__":
    test_homr_resolves_our_guess()
    test_disagreement_on_unguessed_note_still_blocks()
    print("ok resolve")


def _n(m, pos, **k):
    return dict({"measure": m, "duration": "quarter", "dotted": False, "rest": False,
                 "pos": pos}, **k)


def test_accidental_mismatch_takes_homr():
    # 우리: ♮ 로 붙임(B4) / homr: Bb4 — 같은 자리, 다른 임시표 → homr 임시표를 쓴다
    s = {"beats": 4, "sourceFifths": 1, "systems": [{"system": 0, "srcFifths": 1, "notes": [
        _n(1, "G4"), _n(1, "B4"), _n(1, "B4", natural=True), _n(1, "C5")]}]}
    r = merge(s, {"dur": [[["1", "1", "1", "1"]]], "pitch": [[["G4", "B4", "Bb4", "C5"]]],
                  "key": [[1]]})
    b = s["systems"][0]["notes"][2]
    assert r["accAdopted"] == 1 and b["accidental"] == -1 and not b.get("natural")
    assert not s["systems"][0].get("review")


def test_many_accidental_mismatches_block():
    # 어긋난 음이름이 조표대로 맞은 적이 한 번도 없으면 조표 판독이 틀린 것 — 막는다
    s = {"beats": 4, "sourceFifths": 1, "systems": [{"system": 0, "srcFifths": 1, "notes": [
        _n(1, "F4"), _n(1, "B4"), _n(1, "E5"), _n(1, "C5")]}]}
    r = merge(s, {"dur": [[["1", "1", "1", "1"]]], "pitch": [[["F4", "Bb4", "Eb5", "C5"]]],
                  "key": [[1]]})
    assert r["accDiff"] == 3 and any("임시표" in x for x in s["systems"][0]["review"])


def test_undercounted_key_is_fixed():
    # A장조(♯3)를 ♯2 로 읽었다 — G 가 둘 다 G# 로 어긋난다 → 조표를 3 으로
    s = {"beats": 4, "sourceFifths": 3, "systems": [{"system": 0, "srcFifths": 2, "notes": [
        _n(1, "G4"), _n(1, "A4"), _n(1, "G4"), _n(1, "F4")]}]}
    r = merge(s, {"dur": [[["1", "1", "1", "1"]]], "pitch": [[["G#4", "A4", "G#4", "F#4"]]],
                  "key": [[3]]})
    assert s["systems"][0]["srcFifths"] == 3 and r["accDiff"] == 0
    assert not s["systems"][0].get("review")


if __name__ == "__main__":
    test_accidental_mismatch_takes_homr(); test_many_accidental_mismatches_block()
    test_undercounted_key_is_fixed(); print("ok pitch")


def test_agreed_short_first_measure_is_pickup():
    s = {"beats": 4, "systems": [{"system": 0, "notes": [
        dict(_n(1, "C5"), duration="16th"), dict(_n(1, "D5"), duration="16th"),
        dict(_n(1, "E5"), duration="eighth"),
        _n(2, "C5"), _n(2, "C5"), _n(2, "C5"), _n(2, "C5")]}]}
    merge(s, [[["0.25", "0.25", "0.5"], ["1", "1", "1", "1"]]])
    assert s["systems"][0]["pickups"] == [1]
    # homr 가 다르게 읽었으면 봐 주지 않는다
    s["systems"][0].pop("pickups")
    for n in s["systems"][0]["notes"]:
        n.pop("crossChecked", None)
    merge(s, [[["0.25", "0.25", "0.25"], ["1", "1", "1", "1"]]])
    assert "pickups" not in s["systems"][0]


if __name__ == "__main__":
    test_agreed_short_first_measure_is_pickup(); print("ok pickup")


def test_faint_dot_pair_follows_homr():
    def e(**k):
        return dict({"measure": 1, "duration": "eighth", "dotted": False, "rest": False}, **k)
    notes = [e(dotScore=0.4), e(), e(), e(), dict(e(), duration="half")]
    s = {"beats": 4, "systems": [{"system": 0, "notes": notes}]}
    r = merge(s, [[["0.75", "0.25", "0.5", "0.5", "2"]]])
    assert r.get("resolved") == 1 and notes[0]["dotted"] and notes[1]["duration"] == "16th"
    # 점 흔적이 없으면 막는다
    notes = [e(), e(), e(), e(), dict(e(), duration="half")]
    s = {"beats": 4, "systems": [{"system": 0, "notes": notes}]}
    r = merge(s, [[["0.75", "0.25", "0.5", "0.5", "2"]]])
    assert r["conflict"] == 1 and not notes[0]["dotted"]


if __name__ == "__main__":
    test_faint_dot_pair_follows_homr(); print("ok dot")


def test_guessed_measure_takes_homr_with_same_heads():
    def e(d, **k):
        return dict({"measure": 1, "duration": d, "dotted": False, "rest": False}, **k)
    # 우리: 첫 음을 4분으로 찍었다 / homr: 8분쉼표 + 8분 — 머리 수 같음
    notes = [e("quarter", guessed=True)] + [e("eighth") for _ in range(6)]
    s = {"beats": 4, "systems": [{"system": 0, "notes": notes}]}
    r = merge(s, [[["r0.5"] + ["0.5"] * 7]])
    got = s["systems"][0]["notes"]
    assert r.get("homrGuess") == 1 and got[0]["rest"] and got[1]["duration"] == "eighth"
    assert not any(n.get("guessed") for n in got)


if __name__ == "__main__":
    test_guessed_measure_takes_homr_with_same_heads(); print("ok guess")


def test_extra_head_dropped_by_pitch():
    def q(pos, d="quarter"):
        return {"measure": 1, "duration": d, "dotted": False, "rest": False, "pos": pos}
    # 우리: ♩=(A5 자리 헛머리) + 온음표 + 4분 → 6박 / homr: 온음표 하나(F4)
    notes = [q("A5"), q("F4", "whole"), q("C4")]
    s = {"beats": 4, "systems": [{"system": 0, "notes": notes}]}
    r = merge(s, {"dur": [[["4"]]], "pitch": [[["F4"]]], "key": [[0]]})
    got = s["systems"][0]["notes"]
    assert r.get("dropped") == 1 and len(got) == 1 and got[0]["pos"] == "F4"
    # 같은 음이 둘이라 어느 머리를 버릴지 모르면 손대지 않는다
    notes = [q("F4"), q("F4"), q("G4", "whole")]
    s = {"beats": 4, "systems": [{"system": 0, "notes": notes}]}
    r = merge(s, {"dur": [[["2", "2"]]], "pitch": [[["F4", "G4"]]], "key": [[0]]})
    assert not r.get("dropped")


if __name__ == "__main__":
    test_extra_head_dropped_by_pitch(); print("ok drop")
