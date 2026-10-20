"""
**"한 단계 옮기기" 174개는 어느 음가에서, 어느 방향으로 틀리나.**

한 단계 차이는 원인이 둘로 갈린다.
  8분 <-> 4분  : 꼬리·빔을 잘못 셌다 (_level_and_beam)
  4분 <-> 2분  : 머리 속이 빈 것을 찬 것으로 봤다 (검출 class)
  2분 <-> 온음표: 같은 속 빈 머리 — 기둥 유무

고치는 자리가 완전히 다르므로 섞어 세면 방향을 못 정한다.
"""
import json, os, collections

DUR = {"whole": 32, "half": 16, "quarter": 8, "eighth": 4, "16th": 2}
ORDER = ["16th", "eighth", "quarter", "half", "whole"]


def measures(st):
    for si, s in enumerate(st.get("systems") or []):
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


pairs, dirs, rests = collections.Counter(), collections.Counter(), 0
uniq, total = 0, 0
for f in sorted(os.listdir("eval/structs")):
    if not f.endswith(".json"):
        continue
    st = json.load(open(f"eval/structs/{f}"))
    if not st.get("systems"):
        continue
    full = int(round(float(st.get("beats") or 4) * 8))
    for si, mi, ns in measures(st):
        got = sum(units(n) for n in ns)
        gap = full - got
        if gap == 0 or not ns:
            continue
        # 점으로 설명되면 그쪽 줄기다 — 여기서는 뺀다
        if any(not n.get("dotted") and DUR.get(n.get("duration"), 0) // 2 == gap
               for n in ns):
            continue
        hits = []
        for n in ns:
            d = n.get("duration")
            if d not in ORDER:
                continue
            i = ORDER.index(d)
            for j in (i - 1, i + 1):
                if not (0 <= j < len(ORDER)):
                    continue
                delta = (DUR[ORDER[j]] - DUR[d]) * (3 if n.get("dotted") else 2) // 2
                if delta == gap:
                    hits.append((d, ORDER[j], bool(n.get("rest"))))
        if not hits:
            continue
        total += 1
        if len(hits) == 1:
            uniq += 1
        frm, to, is_rest = hits[0]
        pairs[f"{frm} → {to}"] += 1
        dirs["길게 읽어야" if DUR[to] > DUR[frm] else "짧게 읽어야"] += 1
        rests += 1 if is_rest else 0

print(f"'한 단계 옮기기'로 설명되는 마디 {total}개 "
      f"(후보가 하나뿐인 마디 {uniq}, {uniq/max(1,total):.0%})\n")
print("방향")
for k, v in dirs.most_common():
    print(f"  {v:5}  {v/max(1,total):5.0%}  {k}")
print("\n어느 음가에서 (첫 후보 기준)")
for k, v in pairs.most_common(12):
    print(f"  {v:5}  {v/max(1,total):5.0%}  {k}")
print(f"\n쉼표였던 경우 {rests} ({rests/max(1,total):.0%})")
