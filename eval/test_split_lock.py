"""단 경계에서 이미 짝이 맞는 반쪽 마디는 혼자 채우지 않는다."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import fitdur as F

def m(durs, rest=0.0):
    return {"notes": [{"duration": d} for d in durs], "rest": rest}

# 단1 마지막 3박 + 단2 첫 1박 = 4박 — 정상 짝이므로 둘 다 그대로여야 한다
s = [[m(["quarter"]*4), m(["quarter"]*3)],
     [m(["eighth","eighth"]), m(["quarter"]*4)]]
F.fit_page(s, 4.0)
assert [n["duration"] for n in s[0][1]["notes"]] == ["quarter"]*3, s[0][1]
assert [n["duration"] for n in s[1][0]["notes"]] == ["eighth"]*2, s[1][0]

# 짝이 안 맞으면(3박 + 0.5박) 합쳐서 역산하는 기존 동작은 살아 있어야 한다
s2 = [[m(["quarter"]*4), m(["quarter"]*3)],
      [m(["eighth"]), m(["quarter"]*4)]]
r = F.fit_page(s2, 4.0)
assert r["joined"] >= 1 or r["alone"] >= 1, r

# 단 안쪽 마디는 잠금과 무관하게 고쳐진다
s3 = [[m(["quarter"]*4), m(["quarter"]*3), m(["quarter"]*4)]]
F.fit_page(s3, 4.0)
assert F._beats(s3[0][1]) == 4.0, s3[0][1]
print("ok")

# promote_dots 도 짝 맞는 반쪽 마디는 건드리지 않는다
d = lambda: {"duration": "half", "dotScore": 0.5}
s4 = [[m(["quarter"]*4), {"notes": [d(), {"duration": "half"}], "rest": 0.0}],
      [m(["quarter"]), m(["quarter"]*4)]]
s4[0][1]["notes"] = [{"duration": "half", "dotScore": 0.5},
                     {"duration": "quarter", "dotScore": 0.0}]   # 3박
F.promote_dots(s4, 4.0)
assert not s4[0][1]["notes"][0].get("dotted"), s4[0][1]
print("ok — promote_dots 잠금")

# NEAR 밖 edge 마디 — 답이 유일하면 고치고, 갈리면 그대로 둔다
s5 = [[m(["quarter"]*4), m(["quarter", "quarter"])]]     # 끝마디 2.0박
F.fit_page(s5, 4.0)                                       # 유일해 [half, half]
assert [n["duration"] for n in s5[0][1]["notes"]] == ["half", "half"], s5[0][1]

s6 = [[m(["quarter"]*4), m(["eighth", "quarter", "quarter"])]]   # 끝마디 2.5박
F.fit_page(s6, 4.0)                                       # 답이 둘 — 그대로 둔다
assert [n["duration"] for n in s6[0][1]["notes"]] == ["eighth", "quarter", "quarter"], s6[0][1]

# 곡의 첫 마디(못갖춘마디)는 NEAR 밖이면 손대지 않는다
s7 = [[m(["eighth"]), m(["quarter"]*4)]]
F.fit_page(s7, 4.0)
assert F._beats(s7[0][0]) == 0.5, s7[0][0]
print("ok — edge 유일해만 수리 · 못갖춘마디 보존")
