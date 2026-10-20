"""반복 비교: 같은 그림을 두 번 다르게 읽었으면 한쪽이 틀렸다."""
import sys, os
import numpy as np
sys.path.insert(0, os.path.dirname(__file__))
import repeats as R

def items(spec):
    """'[q]essq.' 같은 문자열을 items 로. []=쉼표, .=붙임점"""
    M = {"o":"whole","h":"half","q":"quarter","e":"eighth","s":"16th"}
    out, i = [], 0
    while i < len(spec):
        rest = spec[i] == "["
        if rest: i += 1
        d = M[spec[i]]; i += 1
        dot = i < len(spec) and spec[i] == "."
        if dot: i += 1
        if rest:
            assert spec[i] == "]"; i += 1
        out.append({"duration": d, "dotted": dot, "rest": rest})
    return out

# ① 리듬 비교 — 쉼표 유무를 구분한다
assert R._rhythm_of(items("[q]ess")) != R._rhythm_of(items("qess"))
assert R._rhythm_of(items("qq")) == R._rhythm_of(items("qq"))

# ② 음가 합 (8분음표 = 4눈금, 4/4 = 32)
assert R._units(items("qqqq")) == 32
assert R._units(items("[q]essq.ss")) == 32, R._units(items("[q]essq.ss"))

# ③ 손댄 자리 세기
a = items("qqqq"); a[0]["fitted"] = True; a[1]["guessed"] = True
assert R._touched(a) == 2 and R._touched(items("qqqq")) == 0

# ④ 리듬 옮기기 — 음높이는 대상 것을 순서대로 쓴다
src = items("[q]eeqq")                      # 쉼표 + 음표 4개
dst = items("qqqq")                          # 음표 4개
for k, n in enumerate(dst): n["head"] = {"x": k * 10.0}
R._copy_rhythm(src, dst)
assert [x["rest"] for x in dst] == [True, False, False, False, False]
assert [x["duration"] for x in dst] == ["quarter","eighth","eighth","quarter","quarter"]
assert [x["head"]["x"] for x in dst if not x["rest"]] == [0.0, 10.0, 20.0, 30.0], "음높이 순서가 보존돼야 한다"
assert all(x.get("repeatFixed") for x in dst)

# ⑤ 고친 뒤 fitted 표시는 지운다 — 더 이상 추정이 아니다
assert not any(x.get("fitted") for x in dst)

# ⑥ 실제 수리: 단1(손 안 댐) 을 믿고 단2(손 댐) 를 고친다
def page(spec, touched=False):
    it = items(spec)
    if touched:
        for x in it: x["fitted"] = True
    return [{"items": it, "notes": [], "rest": 0.0}]

pages = [page("[q]essq.ss"), page("qeeq.ss", touched=True)]
class S:  # 가짜 staff — find_pairs 를 건너뛰려고 직접 부른다
    top, bottom, left, right = 0, 10, 0, 10
before = R._rhythm_of(pages[1][0]["items"])
# find_pairs 를 우회해 짝을 직접 준다
import types
orig = R.find_pairs
R.find_pairs = lambda *a, **k: [(0, 1, 0.9)]
n = R.repair(pages, np.zeros((20, 20), dtype=bool), [S(), S()], 10.0)
R.find_pairs = orig
assert n == 1, n
assert R._rhythm_of(pages[1][0]["items"]) == R._rhythm_of(pages[0][0]["items"]), "믿는 쪽으로 맞춰져야 한다"
assert R._rhythm_of(pages[1][0]["items"]) != before

# ⑦ **한쪽만 4박이면 그쪽을 믿는다** — 깨진 짝을 멀쩡한 짝으로 고친다
pages2 = [page("qqqq"), page("eeee")]         # 4박 vs 2박, 음표는 둘 다 4개
R.find_pairs = lambda *a, **k: [(0, 1, 0.9)]
n2 = R.repair(pages2, np.zeros((20, 20), dtype=bool), [S(), S()], 10.0)
R.find_pairs = orig
assert n2 == 1, "4박인 쪽으로 고쳐야 한다"
assert R._units(pages2[1][0]["items"]) == 32, pages2[1][0]["items"]

# ⑧ 둘 다 4박이 아니면 고르지 않는다 — 어느 쪽도 믿을 근거가 없다
pages3 = [page("qqq"), page("eee")]           # 3박 vs 1.5박, 둘 다 4박 아님
R.find_pairs = lambda *a, **k: [(0, 1, 0.9)]
n3 = R.repair(pages3, np.zeros((20, 20), dtype=bool), [S(), S()], 10.0)
R.find_pairs = orig
assert n3 == 0, "둘 다 4박이 아니면 손대지 않는다"

# ⑨ 음표 수가 다르면 고치지 않는다 — 음높이를 짝지을 수 없다
pages4 = [page("qqqq"), page("qq")]
R.find_pairs = lambda *a, **k: [(0, 1, 0.9)]
n4 = R.repair(pages4, np.zeros((20, 20), dtype=bool), [S(), S()], 10.0)
R.find_pairs = orig
assert n4 == 0, "음표 수가 다르면 손대지 않는다"
assert all(x.get("repeatDiff") for x in pages4[1][0]["items"]), "표시는 남겨야 한다"

print("ok — 반복 비교 · 리듬 이식 · 4박 우선 · 근거 없으면 보류")
