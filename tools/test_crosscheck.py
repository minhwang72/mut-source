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
