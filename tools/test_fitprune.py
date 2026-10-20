"""그림과 모순되는 답은 쓰지 않는다 — 그러나 거른 덕에 남은 답은 여전히 짐작이다."""
import sys
sys.path.insert(0, "tools")
from fitdur import _apply


def n(d, beam=-1, hollow=None):
    return {"duration": d, "dotted": False, "beamGroup": beam, "hollow": hollow, "x": 0}


def measure(ns):
    for i, x in enumerate(ns):
        x["x"] = i
    return {"notes": ns, "rest": 0.0, "items": list(ns)}


def test_pruned_answer_is_still_a_guess():
    # 8분 8분(빔) 4분 4분 = 3박. 답 후보 4개 중 그림과 맞는 건 하나뿐이지만
    # 그건 "반증이 없다"일 뿐이다 — 짐작 표시를 남겨 과금을 막는다.
    ns = [n("eighth", 0), n("eighth", 0), n("quarter", hollow=0.6), n("quarter", hollow=0.0)]
    m = measure(ns)
    assert _apply(m, 32)
    assert [x["duration"] for x in ns] == ["eighth", "eighth", "half", "quarter"]
    assert ns[2]["guessed"]


def test_contradicted_unique_answer_is_refused():
    # 실측 camp0814a-3: 2분 + 8분 8분(빔) = 3박. 유일한 답은 "8분 → 4분"인데
    # 빔에 묶인 음이라 그림과 모순 — 고치지 않고 깨진 채 둔다(게이트가 막는다).
    ns = [n("half", hollow=0.4), n("eighth", 0), n("eighth", 0)]
    m = measure(ns)
    assert not _apply(m, 32, guess=False)
    assert [x["duration"] for x in ns] == ["half", "eighth", "eighth"]


def test_unique_uncontradicted_answer_is_fitted():
    ns = [n("half", hollow=0.6), n("quarter", hollow=0.0)]   # 3박, 답은 4분→2분뿐
    m = measure(ns)
    ns[1]["hollow"] = None                                   # 반증 없음
    assert _apply(m, 32)
    assert ns[1]["duration"] == "half" and ns[1]["fitted"] and not ns[1].get("guessed")


if __name__ == "__main__":
    test_pruned_answer_is_still_a_guess()
    test_contradicted_unique_answer_is_refused()
    test_unique_uncontradicted_answer_is_fitted()
    print("ok")


def test_sure_rest_and_seen_sixteenth_are_not_stretched():
    # day2sb-1 단6: 확신 0.80 8분쉼표·2차 빔 16분을 늘려 합을 맞추던 것을 막는다
    r = {"duration": "eighth", "dotted": False, "rest": True, "conf": 0.80, "x": 0}
    q = n("quarter"); q["x"] = 1
    half_r = {"duration": "half", "dotted": False, "rest": True, "conf": 0.46, "x": -1}
    m = {"notes": [q], "rest": 2.5, "items": [half_r, r, q]}
    assert not _apply(m, 32)
    a, b = n("16th", 0), n("16th", 0)
    a["level"] = b["level"] = 2           # 둘이 2차 빔을 나눈다 — 진짜 16분
    c, d = n("quarter"), n("half")
    for i, x in enumerate((c, a, b, d)):
        x["x"] = i
    m = {"notes": [c, a, b, d], "rest": 0.0, "items": [c, a, b, d]}
    assert not _apply(m, 32)
    assert a["duration"] == b["duration"] == "16th"


if __name__ == "__main__":
    test_sure_rest_and_seen_sixteenth_are_not_stretched()
    print("ok sure")



def test_lone_level2_stub_can_be_stretched():
    # wish0809-7 단0: [8,8,8,16] — 형광펜 띠로 한 음에만 생긴 2차 빔 조각
    ns = [n("eighth", 3), n("eighth", 3), n("eighth", 3), n("16th", 3),
          n("quarter"), n("eighth")]
    ns[3]["level"] = 2
    for i, x in enumerate(ns):
        x["x"] = i
    r = {"duration": "eighth", "dotted": False, "rest": True, "conf": 0.83, "x": 4.5}
    m = {"notes": ns, "rest": 0.5, "items": ns[:5] + [r, ns[5]]}
    assert _apply(m, 32)
    assert ns[3]["duration"] == "eighth"


if __name__ == "__main__":
    test_lone_level2_stub_can_be_stretched()
    print("ok stub")
