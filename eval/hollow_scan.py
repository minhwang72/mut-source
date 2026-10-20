"""
**4분음표로 읽은 머리 중 실제로 속이 빈 것이 얼마나 되나.**

박자와 무관하게 전수로 잰다. 앞선 분석은 "한 단계 옮기면 합이 맞는 음표"를
고른 것이라 산술이 만든 헛후보가 섞인다(half->whole 인데 기둥이 있었다).
여기서는 **화소만** 본다 — 머리 속이 밝으면 속 빈 머리다. 그게 사실이면
박자를 안 보고도 고칠 수 있다.

지표 = 머리 가운데 밝기 - 머리 테두리 잉크. 속이 비면 크고, 꽉 차면 0 에
가깝다. 인쇄 농도에 흔들리지 않게 그 머리 자신의 잉크로 잰다.
"""
import os, sys, warnings, collections
sys.path.insert(0, "tools"); sys.path.insert(0, "server")
warnings.filterwarnings("ignore")
import numpy as np
import local_reader as LR
from PIL import Image

PAGES = sys.argv[1:] or sorted(
    f"악보샘플/이미지/{f}" for f in os.listdir("악보샘플/이미지")
    if f.endswith(".png"))[:20]

by_dur = collections.defaultdict(list)
for p in PAGES:
    try:
        ex = LR.read_sheet_local(open(p, "rb").read())
    except Exception:                            # noqa: BLE001
        continue
    g = np.asarray(Image.open(p).convert("L")).astype(float)
    scale = float((ex.get("geometry") or {}).get("scale") or 1.0)
    for s in (ex["struct"].get("systems") or []):
        for n in (s.get("notes") or []):
            if n.get("rest") or "head" not in n:
                continue
            h = n["head"]
            x, y = h["x"] / scale, h["y"] / scale
            w, hh = h["w"] / scale, h["h"] / scale
            core = g[int(y + hh * .32):int(y + hh * .68),
                     int(x + w * .32):int(x + w * .68)]
            edge = g[int(y):int(y + hh), int(x):int(x + w)]
            if core.size == 0 or edge.size == 0:
                continue
            by_dur[n.get("duration")].append(
                float(core.mean() - np.percentile(edge, 10)))

print(f"{'읽은 음가':10} {'개수':>5} {'중앙값':>7} {'25%':>6} {'75%':>6} {'속빔>60':>8}")
for d in ("16th", "eighth", "quarter", "half", "whole"):
    v = sorted(by_dur.get(d, []))
    if not v:
        continue
    n = len(v)
    hi = sum(1 for x in v if x > 60)
    print(f"{d:10} {n:5} {v[n//2]:7.0f} {v[n//4]:6.0f} {v[3*n//4]:6.0f} "
          f"{hi:5} {hi/n:4.0%}")

q = sorted(by_dur.get("quarter", []))
print(f"\n4분음표로 읽은 머리 {len(q)}개 중 속이 빈 것")
for cut in (40, 60, 80, 100, 120):
    n = sum(1 for x in q if x > cut)
    print(f"  지표 > {cut:3}  {n:5}개 ({n/max(1,len(q)):4.1%})")
h = sorted(by_dur.get("half", []) + by_dur.get("whole", []))
if h:
    print(f"\n비교: half·whole 로 읽은 머리 {len(h)}개 — "
          f"5% {h[len(h)//20]:.0f} · 중앙값 {h[len(h)//2]:.0f}")
e = sorted(by_dur.get("eighth", []))
if e:
    print(f"      eighth 로 읽은 머리 {len(e)}개 — "
          f"중앙값 {e[len(e)//2]:.0f} · 95% {e[19*len(e)//20]:.0f}")
