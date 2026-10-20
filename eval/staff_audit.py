"""
**오선을 통째로 놓친 장이 얼마나 되나.**

정답 단 수를 모르지만, 단 간격은 한 장 안에서 거의 일정하다. 간격이
중앙값의 1.6배를 넘으면 그 사이에 단이 빠진 것이다(실측: wish0809-4 에서
간격 155 사이에 366·301 이 있었고, 9단 중 6단만 잡혔다).

오선을 놓치면 **그 아래 전부가 틀린다** — 가사 띠가 다음 단을 삼키고,
음표가 엉뚱한 단에 배정되고, 마디 검산이 무의미해진다.
"""
import sys, os, glob, warnings
sys.path.insert(0, "tools"); sys.path.insert(0, "server")
warnings.filterwarnings("ignore")
import numpy as np, statistics as S
import prepare, sheetcv as cv

bad = []
tot_miss = tot_found = 0
import statistics
ALL = sorted(glob.glob("악보샘플/이미지/*.png"))
counts = []
for p in ALL:
    name = os.path.basename(p)[:-4]
    try:
        img = prepare.load(open(p, "rb"))
        rep, img, ink, staves = prepare.analyze_image(img)
    except Exception as e:
        print(f"{name}: 건너뜀 ({str(e)[:40]})", flush=True); continue
    tops = [s.top for s in staves]
    tot_found += len(tops)
    counts.append((name, len(tops)))
    if len(tops) < 3:
        print(f"{name}: 단 {len(tops)}개뿐", flush=True); continue
    gaps = [b - a for a, b in zip(tops, tops[1:])]
    # **최소 간격을 주기로 본다.** 중앙값을 쓰면 많이 놓친 장일수록 주기가
    # 부풀어 구멍이 안 보인다(실측: wish0809-4 는 9단 중 6단만 잡혔는데
    # 중앙값 기준으로는 "빠짐 0"으로 셌다).
    med = min(gaps)
    miss = 0
    holes = []
    for a, g in zip(tops, gaps):
        k = round(g / med) if med else 1
        if k >= 2 and g > med * 1.6:
            miss += k - 1
            holes.append((a, g, k - 1))
    tot_miss += miss
    # 오선 높이(4칸)가 들쭉날쭉한 것도 신호다
    hs = [s.bottom - s.top for s in staves]
    odd = [round(h / 4, 1) for h in hs if abs(h - S.median(hs)) > S.median(hs) * 0.15]
    if miss or odd:
        bad.append((name, len(tops), miss, holes[:3], odd[:4]))
        print(f"{name}: 잡힌 {len(tops)}단 · 빠진 것 추정 {miss} · 간격중앙 {med:.0f} "
              f"· 이상높이 {odd[:4]}", flush=True)

print(f"\n=== {len(counts)}장 · 잡힌 단 {tot_found} · 빠졌다고 추정 {tot_miss}")
from collections import Counter
print("  장별 단 수 분포:", dict(sorted(Counter(c for _, c in counts).items())))
few = [(n, c) for n, c in counts if c < 5]
print(f"  단 5개 미만인 장 {len(few)}: {few}")
print(f"문제 있는 장 {len(bad)}")
for n, k, m, holes, odd in sorted(bad, key=lambda r: -r[2])[:12]:
    print(f"  {n:16s} {k}단 · 빠짐 {m} · 구멍 {holes} · 이상높이 {odd}")
