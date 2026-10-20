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

import json, os, collections

DUR = {"whole": 32, "half": 16, "quarter": 8, "eighth": 4, "16th": 2}
ORDER = ["16th", "eighth", "quarter", "half", "whole"]


def units(n):
    v = DUR.get(n.get("duration"), 0)
    return v * 3 // 2 if n.get("dotted") else v


def explained(ns, full):
    """why_offbeat 과 같은 판정 — 여기서 True 면 이미 설명된 것이다."""
    got = sum(units(n) for n in ns)
    gap = full - got
    if gap == 0:
        return True
    for n in ns:
        base = DUR.get(n.get("duration"), 0)
        if not base:
            continue
        if not n.get("dotted") and base // 2 == gap:
            return True
        if n.get("dotted") and -(base // 2) == gap:
            return True
        d = n.get("duration")
        if d in ORDER:
            i = ORDER.index(d)
            for j in (i - 1, i + 1):
                if 0 <= j < len(ORDER):
                    delta = (DUR[ORDER[j]] - DUR[d]) * (3 if n.get("dotted") else 2) // 2
                    if delta == gap:
                        return True
    if gap > 0 and (gap in DUR.values() or gap in [v * 3 // 2 for v in DUR.values()]):
        return True
    if gap < 0 and -gap in DUR.values():
        return True
    return False


tag = collections.Counter()
sums = collections.Counter()
total = 0
for f in sorted(os.listdir("eval/structs")):
    if not f.endswith(".json"):
        continue
    st = json.load(open(f"eval/structs/{f}"))
    if not st.get("systems"):
        continue
    full = int(round(float(st.get("beats") or 4) * 8))
    for s in (st.get("systems") or []):
        per = collections.defaultdict(list)
        for n in s.get("notes") or []:
            if not n.get("chord"):
                per[n.get("measure")].append(n)
        ms = sorted(per)
        tot = {mi: sum(units(n) for n in per[mi]) for mi in ms}
        for k, mi in enumerate(ms):
            ns = per[mi]
            if not ns or explained(ns, full):
                continue
            total += 1
            got = tot[mi]
            prev = tot.get(ms[k - 1]) if k > 0 else None
            nxt = tot.get(ms[k + 1]) if k + 1 < len(ms) else None
            if prev is not None and prev + got == full:
                tag["앞 마디와 합치면 정확히 맞음 (마디선 헛검출)"] += 1
            elif nxt is not None and got + nxt == full:
                tag["뒤 마디와 합치면 정확히 맞음 (마디선 헛검출)"] += 1
            elif got == full * 2:
                tag["기준의 정확히 2배 (마디선 놓침)"] += 1
            elif got > full * 1.5:
                tag["기준의 1.5배 초과 (마디선 놓침 의심)"] += 1
            elif k == 0 or k == len(ms) - 1:
                tag["단의 첫·끝 마디 (줄바꿈에서 쪼개짐 의심)"] += 1
            elif got < full * 0.35:
                tag["기준의 1/3 미만 (검출이 거의 다 놓침)"] += 1
            else:
                tag["그 밖"] += 1
            sums[round((got - full) / 8, 2)] += 1

print(f"설명 안 되는 마디 {total}개\n")
for k, v in tag.most_common():
    print(f"  {v:4}  {v/max(1,total):5.0%}  {k}")
print("\n편차 상위")
for d, v in sums.most_common(10):
    print(f"  {v:4}  {d:+7.2f}박")
