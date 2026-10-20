"""
**가사 음절 수가 음표 수를 말해 주는가.**

쓰기 전에 잰다. 한 음절 = 한 음이 원칙이고, 늘임표(—)도 조각으로 잡히므로
이어지는 음까지 세어질 수 있다. 쉼표에는 가사가 없다.

세 값을 나란히 본다:
  · 음절 : lyricstrip 이 CV 로 나눈 조각 수 (공짜, LLM 0회)
  · LLM  : readcounts 가 읽은 단별 음표 수 (장당 $0.094)
  · 검출 : 검출기가 실제로 잡은 머리 수
음절이 LLM 만큼 맞으면 개수 단서를 공짜로 얻는다.
"""
import sys, os, glob, json, warnings
sys.path.insert(0, "tools"); sys.path.insert(0, "server")
warnings.filterwarnings("ignore")
import numpy as np
from PIL import Image
import prepare, sheetcv as cv, lyricstrip as LS

cache = json.load(open("eval/llm_counts_cache.json"))
rows_all = []
for p in sorted(glob.glob("악보샘플/이미지/*.png")):
    name = os.path.basename(p)[:-4]
    if name not in cache:
        continue
    try:
        img = prepare.load(open(p, "rb"))
        rep, img, ink, staves = prepare.analyze_image(img)
        sp = float(np.median([s.lines[i+1]-s.lines[i]
                              for s in staves for i in range(len(s.lines)-1)]))
        ink_arr = np.asarray(ink)
    except Exception as e:
        print(f"{name}: 건너뜀 ({str(e)[:40]})", flush=True); continue
    c = cache[name]
    rows = (c.get("systems") if isinstance(c, dict) else c) or []
    for i, st in enumerate(staves):
        nxt = staves[i+1].top if i+1 < len(staves) else None
        band = cv.find_lyric_band(ink, st, sp, nxt)
        n_syl = 0
        if band:
            tight = LS.band_of(ink_arr, band, sp, pad_below=True)
            syl = LS.syllables(ink_arr, tight, sp)
            n_syl = len(syl or [])
        r = rows[i] if i < len(rows) else {}
        n_llm = int(r.get("notes") or 0)
        if n_syl == 0 or n_llm == 0:
            continue
        rows_all.append((name, i+1, n_syl, n_llm))
    print(f"{name}: 누적 {len(rows_all)}단", flush=True)

print(f"\n=== 가사 있는 단 {len(rows_all)}개")
if rows_all:
    d = [s - l for _, _, s, l in rows_all]
    import statistics as S
    exact = sum(1 for x in d if x == 0)
    near = sum(1 for x in d if abs(x) <= 1)
    print(f"  음절 == LLM      {exact:4d} ({exact/len(d)*100:.0f}%)")
    print(f"  차이 1 이내       {near:4d} ({near/len(d)*100:.0f}%)")
    print(f"  차이 중앙값 {S.median(d):+.1f} · 평균 {S.mean(d):+.2f} · 표준편차 {S.pstdev(d):.2f}")
    from collections import Counter
    print("  차이 분포:", dict(sorted(Counter(d).items())))
    print("\n  가장 벌어진 단:")
    for n, si, s_, l in sorted(rows_all, key=lambda r: -abs(r[2]-r[3]))[:8]:
        print(f"    {n:16s} 단{si}: 음절 {s_:3d} · LLM {l:3d} ({s_-l:+d})")
