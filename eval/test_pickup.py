"""
곡의 첫 마디가 짧으면 못갖춘마디로 보고 오류로 세지 않는가.

왜: 못갖춘마디는 조판 관행이다. 고전적 판정("첫 마디 + 마지막 마디 = 한
마디")은 이 레퍼토리에 안 맞는다 — 실측 103장 중 첫 마디가 짧은 20장이
**전부** 그 짝이 안 맞았다(콘티는 반복해 부르므로 마지막 마디가 온전하다).
그래서 짝을 요구하지 않고 첫 마디만 면제하되, 면제한 사실은 남긴다.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import checkbeats as CB


def struct(sys_notes):
    return {"systems": [{"notes": ns} for ns in sys_notes]}


Q = {"duration": "quarter", "dotted": False, "rest": False}
full4 = [dict(Q, measure=m) for m in (1, 1, 1, 1, 2, 2, 2, 2)]

# ── 첫 마디가 1박이면 못갖춘마디 — under 에 안 들어간다
s = struct([[dict(Q, measure=1)] + [dict(Q, measure=m) for m in (2,2,2,2)]])
r = CB.check(s, 4)
assert r["pickup"] is not None, "못갖춘마디를 못 알아봤다"
assert not any(u[0] == 0 and u[1] == 1 for u in r["under"]), r["under"]
assert r["ok"] == 1, r["ok"]

# ── **가운데 마디가 짧은 건 여전히 오류다** (면제는 첫 마디만)
s2 = struct([[dict(Q, measure=m) for m in (1,1,1,1)] + [dict(Q, measure=2)]
             + [dict(Q, measure=m) for m in (3,3,3,3)]])
r2 = CB.check(s2, 4)
assert r2["pickup"] is None, "첫 마디가 온전한데 못갖춘마디로 봤다"
assert any(u[1] == 2 for u in r2["under"]), r2["under"]

# ── 둘째 단의 첫 마디는 면제 대상이 아니다 (쪼개진 마디는 splits 가 본다)
s3 = struct([[dict(Q, measure=m) for m in (1,1,1,1)],
             [dict(Q, measure=1)] + [dict(Q, measure=m) for m in (2,2,2,2)]])
r3 = CB.check(s3, 4)
assert r3["pickup"] is None
assert any(u[0] == 1 and u[1] == 1 for u in r3["under"]), r3["under"]

print("ok")
