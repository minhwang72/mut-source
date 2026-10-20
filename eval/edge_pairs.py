"""
**줄바꿈에서 쪼개진 마디를 오류로 세고 있나.**

한 마디가 줄 끝에서 잘려 다음 줄로 이어지면, 각각은 기준 박에 모자라지만
**둘을 합치면 정확히 맞는다.** 그건 정상 표기지 오류가 아니다.

설명 안 되는 마디의 45%가 단의 첫·끝 마디였다. 앞 단의 마지막 마디와
다음 단의 첫 마디를 이어 붙여 합이 맞는지 센다. 맞으면 그 마디들은
**틀린 게 아니라 게이트가 헛되이 막고 있는 것**이다.
"""
import json, os, collections

DUR = {"whole": 32, "half": 16, "quarter": 8, "eighth": 4, "16th": 2}


def units(n):
    v = DUR.get(n.get("duration"), 0)
    return v * 3 // 2 if n.get("dotted") else v


pair_ok = pair_no = 0
edge_bad = 0
examples = []
for f in sorted(os.listdir("eval/structs")):
    if not f.endswith(".json"):
        continue
    st = json.load(open(f"eval/structs/{f}"))
    if not st.get("systems"):
        continue
    full = int(round(float(st.get("beats") or 4) * 8))
    tot = []
    for s in (st.get("systems") or []):
        per = collections.defaultdict(int)
        for n in s.get("notes") or []:
            if not n.get("chord"):
                per[n.get("measure")] += units(n)
        tot.append([per[k] for k in sorted(per)])
    for si in range(len(tot) - 1):
        if not tot[si] or not tot[si + 1]:
            continue
        last, first = tot[si][-1], tot[si + 1][0]
        if last == full and first == full:
            continue
        if last >= full or first >= full:
            continue
        edge_bad += 1
        if last + first == full:
            pair_ok += 1
            if len(examples) < 8:
                examples.append((f[:-5], si + 1, last / 8, first / 8))
        else:
            pair_no += 1

n = max(1, edge_bad)
print(f"단 경계에서 양쪽 다 기준에 못 미치는 자리 {edge_bad}곳")
print(f"  이어 붙이면 정확히 맞음  {pair_ok:4} ({pair_ok/n:.0%})  ← 쪼개진 마디. 오류가 아니다")
print(f"  이어 붙여도 안 맞음      {pair_no:4} ({pair_no/n:.0%})")
print("\n예시 (앞단 끝 + 뒷단 첫 = 기준)")
for name, si, a, b in examples:
    print(f"  {name:16} 단{si} 끝 {a:g}박 + 단{si+1} 첫 {b:g}박")
