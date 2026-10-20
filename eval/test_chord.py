"""화음 묶기가 **박을 한 번만** 세는가, 그리고 연속 음표를 묶지 않는가."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import detstruct as DS, fitdur as F, checkbeats as CB

SP = 20.0


def head(x, y, w=14, h=10, dur="quarter"):
    return {"x": x, "y": y, "w": w, "h": h, "duration": dur, "dotted": False}


# ① 같은 기둥에 3음이 쌓이면 둘은 구성음
ch = [head(100, 100), head(100, 130), head(101, 160)]
assert DS.mark_chords(ch, SP) == 2, "화음을 못 묶었다"
assert [n.get("chord") for n in ch] == [None, True, True]

# ② 가로로 떨어진 연속 음표는 묶지 않는다 (한 칸=20px 이상)
seq = [head(100, 100), head(130, 130), head(160, 160)]
assert DS.mark_chords(seq, SP) == 0, "연속 음표를 화음으로 묶었다"

# ③ 같은 x 라도 세로로 붙어 있으면 중복 검출 — 묶지 않는다
dup = [head(100, 100), head(100, 105)]
assert DS.mark_chords(dup, SP) == 0, "같은 자리 중복을 화음으로 봤다"

# ④ 박은 **기둥당 한 번**만 센다
m = {"notes": [{"duration": "quarter", "dotted": False},
               {"duration": "quarter", "dotted": False, "chord": True},
               {"duration": "quarter", "dotted": False, "chord": True},
               {"duration": "quarter", "dotted": False},
               {"duration": "half", "dotted": False}], "rest": 0}
assert F._beats(m) == 4.0, f"화음이 박을 여러 번 먹었다 ({F._beats(m)})"

# ⑤ checkbeats 도 같은 규칙
st = {"beats": 4, "systems": [{"system": 0, "measures": 1, "notes": [
    {"measure": 1, "duration": "quarter", "rest": False},
    {"measure": 1, "duration": "quarter", "rest": False, "chord": True},
    {"measure": 1, "duration": "quarter", "rest": False, "chord": True},
    {"measure": 1, "duration": "half", "rest": False},
    {"measure": 1, "duration": "quarter", "rest": False},
]}]}
ck = CB.check(st, 4)
assert not (ck.get("over") or ck.get("under")), f"검산이 화음을 여러 번 셌다 {ck}"
print("ok")

# ── 화음이 박자 수리를 막지 않는가 ────────────────────────────────
# 실측으로 드러난 버그: _beats 는 구성음을 빼고 세는데 _apply 는 넣고 맞춰서,
# 화음 쌍으로만 이뤄진 마디는 영영 수리되지 않았다(4박 → 2박인 채로).
import fitdur as F

def _m(dur):
    """dur: [(음가, 화음인가), ...]"""
    return {"notes": [{"duration": d, "dotted": False, "chord": c} for d, c in dur],
            "rest": 0.0}

m = _m([("eighth", False), ("eighth", True)] * 4)      # 8분 화음 4쌍 = 2박
assert abs(F._beats(m) - 2.0) < 1e-9, F._beats(m)
assert F._apply(m, 32), "화음 마디를 수리하지 못했다"
assert abs(F._beats(m) - 4.0) < 1e-9, f"수리 후에도 {F._beats(m)}박"
# 구성음은 자기 기둥과 같은 음가여야 한다 — 다르면 화음이 어긋나게 그려진다
for a, b in zip(m["notes"][::2], m["notes"][1::2]):
    assert a["duration"] == b["duration"], (a["duration"], b["duration"])

# 구성음에 붙임점을 올려 "채웠다"고 세면 안 된다 — 합은 그대로다
sys_ = [[{"notes": [{"duration": "quarter", "dotted": False, "chord": False},
                    {"duration": "quarter", "dotted": False, "chord": True,
                     "dotScore": 0.50}],
          "rest": 0.0}]]
assert F.promote_dots(sys_, 4.0) == 0, "화음 구성음에 붙임점을 올렸다"

print("화음 ok")

# ── 묶은 단은 "화음 미지원" 경고에서 빠지는가 ──────────────────────
# 안 빼면 화음 악보가 전부 needs_review 로 잠겨 저장 버튼이 영영 안 열린다.
import detstruct as DS, sheetcv as _cv

class _St:
    def __init__(s, t, b):
        s.top, s.bottom = t, b
        s.left, s.right = 0, 199

def _head(x, y, w=8, h=6):
    return {"x": float(x), "y": float(y), "w": float(w), "h": float(h),
            "class": "notehead_filled", "conf": 0.9}

sp2 = 10.0
st2 = [_St(100, 140), _St(300, 340)]
# 단0 은 화음 쌍, 단1 은 가로로 이어진 멜로디
bx = [_head(50, 118), _head(50, 130),                # 단0: 쌓임 → 묶임
      _head(40, 318), _head(80, 318), _head(120, 318)]  # 단1: 안 묶임
counts = [{"notes": 2, "rests": 0, "marks": []}, {"notes": 3, "rests": 0, "marks": []}]
meta = {"stacked": [0, 1]}          # 검출 단계는 두 단 모두 의심했다고 치자
import numpy as _np
gray2 = _np.full((400, 200), 255.0, dtype="float32")
out = DS.build_from(bx, st2, gray2 > 128, sp2, gray2, counts, meta=meta)
left = (out.get("unreliable") or {}).get("stacked") or []
assert 0 not in left, f"묶은 단이 아직 경고에 남아 있다: {left}"
assert 1 in left, f"못 묶은 단은 남아야 한다: {left}"
print("경고 필터 ok")

# ── 머리가 넓은 온음표·2분음표 화음도 묶이는가 ────────────────────
# 실측 now0918-8 단11: 온음표 두 개(폭 30·36, 오선간격 18)의 중심이 13.9px
# 떨어져 중심거리 한계(9.0px)를 넘었다. 안 묶이니 4+4=8박이 됐다.
wide = [{"x": 485.4, "y": 4219.2, "w": 30.4, "h": 19.2, "duration": "whole", "dotted": False},
        {"x": 496.7, "y": 4264.5, "w": 35.5, "h": 19.1, "duration": "whole", "dotted": False}]
assert DS.mark_chords(wide, 18.0) == 1, "넓은 머리 화음을 못 묶었다"

# ── 빔으로 이어진 16분음표는 **묶이면 안 된다** (가로로 떨어져 있다)
run16 = [{"x": 100 + i * 20, "y": 100 + i * 6, "w": 22, "h": 12,
          "duration": "16th", "dotted": False} for i in range(4)]
assert DS.mark_chords(run16, 18.0) == 0, "연속 16분음표를 화음으로 묶었다"

print("넓은 머리 ok")
