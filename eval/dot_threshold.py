"""
**붙임점을 놓치는 이유가 문턱인가, 점이 안 보여서인가.**

깨진 마디의 1위 설명은 "점 하나 더하기"(56%)였다. 그런데 원인은 둘로
갈린다.
  · 점수는 나왔는데 문턱을 못 넘었다 → 문턱을 내리면 잡힌다
  · 점수 자체가 0 이다               → 화소로도 안 보인다. 문턱과 무관

지금 문턱은 두 개다.
  DOT_SCORE 0.55 — 이 위면 바로 붙임점으로 인정
  DOT_GRAY  0.40 — 0.40~0.55 는 회색지대. 마디 합이 모자랄 때만
                   박자 심판이 승격시킨다(promote_dots)
0.40 아래는 **후보조차 안 된다.** 진짜 점이 거기 깔려 있으면 영원히 못 잡는다.

어긋난 마디에서 "점을 붙이면 정확히 채워지는" 음표를 찾아, 그 음표의
점수가 어디에 있는지 센다.
"""
import json, os, sys, collections

DUR = {"whole": 32, "half": 16, "quarter": 8, "eighth": 4, "16th": 2}
GRAY, SURE = 0.40, 0.55


def measures(st):
    for s in st.get("systems") or []:
        per = collections.defaultdict(list)
        for n in s.get("notes") or []:
            if n.get("chord"):
                continue
            per[n.get("measure")].append(n)
        for mi, ns in sorted(per.items()):
            yield mi, ns


def units(n):
    v = DUR.get(n.get("duration"), 0)
    return v * 3 // 2 if n.get("dotted") else v


band = collections.Counter()
scores, n_meas, pages = [], 0, set()
multi = 0
for f in sorted(os.listdir("eval/structs")):
    if not f.endswith(".json"):
        continue
    st = json.load(open(f"eval/structs/{f}"))
    if not st.get("systems"):
        continue
    full = int(round(float(st.get("beats") or 4) * 8))
    for mi, ns in measures(st):
        got = sum(units(n) for n in ns)
        gap = full - got
        if gap <= 0 or not ns:
            continue
        # 점 하나로 정확히 메워지는 음표들
        cand = [n for n in ns if not n.get("dotted")
                and DUR.get(n.get("duration"), 0) // 2 == gap]
        if not cand:
            continue
        n_meas += 1
        pages.add(f)
        if len(cand) > 1:
            multi += 1
        best = max(cand, key=lambda n: n.get("dotScore") or 0.0)
        sc = float(best.get("dotScore") or 0.0)
        scores.append(sc)
        band["0 (흔적 없음)" if sc <= 0.0
             else "0 초과 ~ 0.20" if sc < 0.20
             else "0.20 ~ 0.30" if sc < 0.30
             else "0.30 ~ 0.40 (문턱 바로 아래)" if sc < GRAY
             else "0.40 ~ 0.55 (회색지대인데 승격 실패)" if sc < SURE
             else "0.55 이상"] += 1

print(f"'점 하나로 정확히 메워지는' 마디 {n_meas}개 · {len(pages)}장")
print(f"후보가 둘 이상인 마디 {multi}개 ({multi/max(1,n_meas):.0%})\n")
print("그 음표의 붙임점 점수")
for k in ["0 (흔적 없음)", "0 초과 ~ 0.20", "0.20 ~ 0.30",
          "0.30 ~ 0.40 (문턱 바로 아래)",
          "0.40 ~ 0.55 (회색지대인데 승격 실패)", "0.55 이상"]:
    v = band.get(k, 0)
    print(f"  {v:5}  {v/max(1,n_meas):5.0%}  {k}")

nz = sorted(s for s in scores if s > 0)
if nz:
    print(f"\n0 이 아닌 점수 {len(nz)}개 — 중앙값 {nz[len(nz)//2]:.3f} · "
          f"25% {nz[len(nz)//4]:.3f} · 75% {nz[3*len(nz)//4]:.3f}")
for cut in (0.35, 0.30, 0.25, 0.20, 0.15):
    n = sum(1 for s in scores if s >= cut)
    print(f"  문턱을 {cut:.2f} 로 내리면 후보가 되는 마디 {n:4} ({n/max(1,n_meas):4.0%})")
