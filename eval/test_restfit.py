"""
쉼표도 박자 검산으로 고치는가.

왜: 전에는 쉼표 합을 **고정값**으로 두고 음표만 맞췄다. 그런데 쉼표도 똑같이
오독된다 — 4분쉼표(𝄽)와 8분쉼표(𝄾)는 글리프가 닮았고, `fix_rest_class` 는
온/2분만 자리로 가른다. 고정으로 두면 그 마디는 **영영 못 고친다** —
실측 camp0814b-07 단4 마디4: 4분쉼표 자리에 2분쉼표가 들어가 5박이었다.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import fitdur as F


def measure(items):
    """items: [(kind, duration)] — kind 는 'n'(음표) 또는 'r'(쉼표)."""
    notes, its = [], []
    for i, (kind, d) in enumerate(items):
        o = {"duration": d, "dotted": False, "rest": kind == "r", "x": float(i)}
        its.append(o)
        if kind == "n":
            notes.append(o)
    rest = sum(F.value(o["duration"]) for o in its if o["rest"]) / 8.0
    return {"notes": notes, "rest": rest, "items": its}


# ── 4분쉼표 자리에 2분쉼표: 2 + 2 + 0.5 + 0.5 = 5박 → 4박으로 고쳐야 한다
m = measure([("r", "half"), ("r", "half"), ("r", "eighth"), ("n", "eighth")])
assert abs(F._beats(m) - 5.0) < 1e-9, F._beats(m)
assert F._apply(m, 32), "수리 실패"
assert abs(F._beats(m) - 4.0) < 1e-9, f"수리 후 {F._beats(m)}박"
assert abs(m["rest"] - 3.5) < 1e-9, f"쉼표 합이 안 맞는다: {m['rest']}"
assert any(o.get("fitted") for o in m["items"] if o["rest"]), \
    "고친 쉼표에 표시가 없다 — 수정 패널이 못 짚는다"

# ── **이미 맞는 마디는 건드리지 않는다**
ok = measure([("r", "half"), ("n", "half")])
before = [o["duration"] for o in ok["items"]]
F._apply(ok, 32)
assert [o["duration"] for o in ok["items"]] == before, "맞는 마디를 바꿨다"

# ── 쉼표만 있는 마디도 고친다 (온쉼표 자리에 2분쉼표)
only = measure([("r", "half")])
assert F._apply(only, 32), "쉼표뿐인 마디를 못 고쳤다"
assert abs(F._beats(only) - 4.0) < 1e-9, F._beats(only)

# ── items 가 없으면 옛 동작 (쉼표 고정) — 합친 반쪽 마디 경로
# `[{...}] * 3` 은 **같은 dict 세 참조**다 — 각각 따로 만들어야 한다
old = {"notes": [{"duration": "quarter", "dotted": False} for _ in range(3)],
       "rest": 0.0}
assert F._apply(old, 32)
assert abs(F._beats(old) - 4.0) < 1e-9, F._beats(old)

print("ok")
