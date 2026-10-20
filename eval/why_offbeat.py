"""
**어긋난 마디를 무엇으로 설명할 수 있나.**

경고 — 이 표는 **후보**지 **원인**이 아니다. "한 번의 편집으로 합이
맞는가"를 셀 뿐이라, 실제로 틀린 자리와 무관한 편집도 걸린다. 실측:
quarter -> half 후보 56개를 독립 증거(머리 속 비움)로 검증하니 4분으로
읽은 머리 516개 중 속이 빈 것은 9개뿐이었다. 후보가 둘 이상인 마디가
50% 라는 게 이미 경고였다. 여기서 1위가 나오면 **다른 축의 증거로
확인한 뒤** 움직인다.

그리고 **쪼개진 마디를 빼고 센다.** 악보는 마디 중간에서 줄을 바꾸기도
한다. 그러면 앞 단의 마지막 마디와 뒷 단의 첫 마디가 각각 반쪽이 되는데
오류가 아니다. rebuild.js 의 checkBeats 는 이미 이것을 건너뛰는데 이
파일이 안 빼고 있었다 — 그래서 809 vs 662, 22% 를 부풀려 세고 있었다.
"""


def drop_splits(tot: dict, full: int) -> set:
    """
    단 경계에서 쪼개진 마디를 찾아 (단, 마디) 로 낸다. checkbeats.splits
    와 같은 규칙 — 앞 단 끝과 뒷 단 첫이 둘 다 모자라고 합이 정확히 한
    마디면 원래 한 마디다.
    """
    out = set()
    for si in range(max(tot, default=-1)):
        a = tot.get(si) or {}
        b = tot.get(si + 1) or {}
        if not a or not b:
            continue
        la, fb = max(a), min(b)
        if a[la] < full and b[fb] < full and a[la] + b[fb] == full:
            out.add((si, la))
            out.add((si + 1, fb))
    return out

import json, os, sys, collections

DUR = {"whole": 32, "half": 16, "quarter": 8, "eighth": 4, "16th": 2}
ORDER = ["16th", "eighth", "quarter", "half", "whole"]


def measures(struct):
    """(단, 마디, 음표목록). 화음 구성음은 박을 안 먹으므로 뺀다."""
    for si, s in enumerate(struct.get("systems") or []):
        per = collections.defaultdict(list)
        for n in s.get("notes") or []:
            if n.get("chord"):
                continue
            per[n.get("measure")].append(n)
        for mi, ns in sorted(per.items()):
            yield si, mi, ns


def units(n):
    v = DUR.get(n.get("duration"), 0)
    return v * 3 // 2 if n.get("dotted") else v


def explain(ns, full):
    got = sum(units(n) for n in ns)
    gap = full - got
    if gap == 0:
        return None
    # ① 점 하나 더하기 / 빼기
    for n in ns:
        base = DUR.get(n.get("duration"), 0)
        if not base:
            continue
        if not n.get("dotted") and base // 2 == gap:
            return "점 더하기"
        if n.get("dotted") and -(base // 2) == gap:
            return "점 빼기"
    # ② 음표 하나를 한 단계 옮기기
    for n in ns:
        d = n.get("duration")
        if d not in ORDER:
            continue
        i = ORDER.index(d)
        for j in (i - 1, i + 1):
            if 0 <= j < len(ORDER):
                delta = (DUR[ORDER[j]] - DUR[d]) * (3 if n.get("dotted") else 2) // 2
                if delta == gap:
                    return "한 단계 옮기기"
    # ③ 음표가 통째로 빠졌거나 남았다
    if gap > 0 and gap in DUR.values():
        return "음표 하나 빠짐"
    if gap > 0 and gap in [v * 3 // 2 for v in DUR.values()]:
        return "점음표 하나 빠짐"
    if gap < 0 and -gap in DUR.values():
        return "음표 하나 남음"
    return None


SRC = sys.argv[1] if len(sys.argv) > 1 else "eval/structs"
tally, by_gap, pages = collections.Counter(), collections.Counter(), set()
total = 0
for f in sorted(os.listdir(SRC)):
    if not f.endswith(".json"):
        continue
    st = json.load(open(f"{SRC}/{f}"))
    if not st.get("systems"):
        continue
    full = int(round(float(st.get("beats") or 4) * 8))
    tot = {}
    for si, mi, ns in measures(st):
        tot.setdefault(si, {})[mi] = sum(units(n) for n in ns)
    split = drop_splits(tot, full)
    for si, mi, ns in measures(st):
        got = sum(units(n) for n in ns)
        if got == full or not ns or (si, mi) in split:
            continue
        total += 1
        pages.add(f)
        why = explain(ns, full) or "설명 안 됨"
        tally[why] += 1
        by_gap[(why, round((got - full) / 8, 3))] += 1

print(f"어긋난 마디 {total}개 · {len(pages)}장\n")
print("한 번의 편집으로 설명되는가")
for why, n in tally.most_common():
    print(f"  {n:5}  {n/max(1,total):5.0%}  {why}")
print("\n설명별 편차 (상위)")
for (why, d), n in by_gap.most_common(12):
    print(f"  {n:5}  {d:+7.3f}박  {why}")
