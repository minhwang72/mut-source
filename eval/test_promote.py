"""
박자가 모자란 마디에서만 버려진 머리를 되살리는가.

왜: detect_guided 는 LLM 이 준 개수까지만 채운다. 그 개수가 하나 모자라면
고신뢰 검출로 다 차 버려 **진짜 음표가 버려진다**(실측: camp0814a-1 단8
점2분음표 점수 0.059 → 그 마디가 4박에서 1박이 됐다).

지켜야 할 두 가지:
  1. 모자란 마디는 **정확히 채워질 때만** 받는다
  2. **이미 맞는 마디는 절대 건드리지 않는다** — 맞던 게 틀려지면 손해다
"""
import os, sys, warnings
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
warnings.filterwarnings("ignore")
import numpy as np
import detstruct as DS


class St:
    def __init__(s, top, bottom, left=0, right=399):
        s.top, s.bottom, s.left, s.right = top, bottom, left, right
        s.lines = [top + i * 10 for i in range(5)]


def head(x, y, conf=0.9, w=8, h=6):
    return {"x": float(x), "y": float(y), "w": float(w), "h": float(h),
            "class": "notehead_filled", "conf": conf}


SP = 10.0
ST = [St(100, 140)]
GRAY = np.full((260, 400), 255.0, dtype="float32")
STRICT = GRAY > 128


def run(boxes, spare, beats=4.0):
    meta = {"spare": [spare]} if spare is not None else {}
    counts = [{"notes": len(boxes), "rests": 0, "marks": [], "time_signature": "4/4"}]
    return DS.build_from(boxes, ST, STRICT, SP, GRAY, counts, meta=meta, beats=beats)


def sums(out):
    V = DS.BEATS
    per = {}
    for s_ in out.get("systems") or []:
        for n in s_.get("notes") or []:
            if n.get("chord") or n.get("rest"):
                continue
            m = n.get("measure", 1)
            per[m] = per.get(m, 0) + V[n["duration"]] * (1.5 if n.get("dotted") else 1)
    return [round(per[k], 2) for k in sorted(per)]


# ── ① 3박짜리 마디 + 버려진 머리 하나 → 4박이 되면 받는다
notes = [head(40 + i * 30, 118) for i in range(3)]
lost = head(130, 118, conf=0.06)
before = run(notes, [])
after = run(notes, [lost])
assert after.get("headsPromoted") == 1, f"되살리지 못했다 ({after.get('headsPromoted')})"
# 합은 fitdur 가 음가를 늘려 어차피 4박을 맞춘다 — 차이는 **음표 수**다.
# 되살리지 않으면 음표 3개를 4박에 늘려 리듬이 통째로 틀린다.
cnt = lambda o: sum(len(x.get("notes") or []) for x in (o.get("systems") or []))
assert cnt(after) == cnt(before) + 1, (cnt(before), cnt(after))
assert any(n.get("headPromoted") for x in after["systems"] for n in x["notes"]), \
    "되살린 자리에 표시가 없다 — 화면이 짚어 주지 못한다"

# ── ② 이미 4박이면 건드리지 않는다
full = [head(40 + i * 30, 118) for i in range(4)]
keep = run(full, [head(160, 118, conf=0.06)])
assert keep.get("headsPromoted") == 0, "맞는 마디에 머리를 밀어 넣었다"

# ── ③ 점수가 너무 낮으면 잉크가 아니라 잡음이다
noise = run(notes, [head(130, 118, conf=0.001)])
assert noise.get("headsPromoted") == 0, "잡음을 음표로 받았다"

# ── ④ 여분이 없으면 아무 일도 없다
assert run(notes, []).get("headsPromoted") == 0

print("ok")

# ── 음자리표·조표 구간의 '쉼표'는 버린다 ──────────────────────────
# 조표의 ♭ 는 8분쉼표와 글리프가 닮아 자주 뒤바뀐다 — 실측 camp0814b-07 단7:
# 조표 ♭ 가 rest_8th(0.57)로 잡혀 **0.5박짜리 유령 마디**가 생겼고, 그 위치
# 때문에 도돌이표까지 마디선으로 읽혔다.
# **음표는 버리지 않는다** — 머리 구간을 조금만 길게 잡아도 진짜 첫 음을
# 잃는다(실측 105장: 음표까지 버리면 9장 개선 · 8장 후퇴로 무승부,
# 쉼표만 버리면 5장 개선 · 1장 후퇴).
def rest(x, cls="rest_8th"):
    return {"x": float(x), "y": 110.0, "w": 8.0, "h": 12.0, "class": cls, "conf": 0.6}

HEAD_END = 80
boxes_hz = [rest(40), head(120, 118), head(150, 118), head(180, 118), head(210, 118)]
out_off = run(boxes_hz, [])                      # head_ends 없음 → 쉼표가 남는다
counts_hz = [{"notes": 4, "rests": 1, "marks": [], "time_signature": "4/4"}]
out_on = DS.build_from(boxes_hz, ST, STRICT, SP, GRAY, counts_hz,
                       meta={}, beats=4.0, head_ends=[HEAD_END])
rests_on = sum(1 for s in out_on["systems"] for n in s["notes"] if n.get("rest"))
assert rests_on == 0, f"머리 구간 쉼표를 안 버렸다 ({rests_on})"

# 머리 구간 **오른쪽**의 쉼표는 남는다
boxes_ok = [rest(120), head(150, 118), head(180, 118), head(210, 118)]
counts_ok = [{"notes": 3, "rests": 1, "marks": [], "time_signature": "4/4"}]
keep = DS.build_from(boxes_ok, ST, STRICT, SP, GRAY, counts_ok,
                     meta={}, beats=4.0, head_ends=[HEAD_END])
assert sum(1 for s in keep["systems"] for n in s["notes"] if n.get("rest")) == 1, \
    "머리 구간 밖 쉼표까지 버렸다"

# **음표는 머리 구간 안이어도 안 버린다**
boxes_nh = [head(40, 118), head(120, 118), head(150, 118), head(180, 118)]
counts_nh = [{"notes": 4, "rests": 0, "marks": [], "time_signature": "4/4"}]
nh = DS.build_from(boxes_nh, ST, STRICT, SP, GRAY, counts_nh,
                   meta={}, beats=4.0, head_ends=[HEAD_END])
assert sum(len(s["notes"]) for s in nh["systems"]) == 4, "머리 구간 음표를 버렸다"

print("머리 구간 ok")
