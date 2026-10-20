"""
**4분음표로 읽힌 머리가 실제로 속이 비었나 — 눈으로 본다.**

"한 단계 옮기기" 185개 중 46%가 quarter->half 또는 half->whole 이다.
둘 다 **속 빈 머리**를 찬 머리로 잘못 본 것이면 설명이 되는데, 그건
가설이다. 붙임점 때 지표만 보고 갔으면 거짓 점 79개를 넣을 뻔했으므로
이번에도 화소를 먼저 본다.

합이 모자란 마디에서 "이 음표를 한 단계 길게 읽으면 정확히 맞는" 머리를
찾아, 그 머리를 잘라 붙인다. 속이 비어 있으면 가설이 맞는 것이고,
꽉 차 있으면 다른 원인이다.
"""
import os, sys, warnings, collections
sys.path.insert(0, "tools"); sys.path.insert(0, "server")
warnings.filterwarnings("ignore")
import numpy as np
import local_reader as LR
from PIL import Image, ImageDraw

DUR = {"whole": 32, "half": 16, "quarter": 8, "eighth": 4, "16th": 2}
ORDER = ["16th", "eighth", "quarter", "half", "whole"]
WANT = {("quarter", "half"), ("half", "whole")}

PAGES = sys.argv[1:] or sorted(
    f"악보샘플/이미지/{f}" for f in os.listdir("악보샘플/이미지")
    if f.endswith(".png"))[:24]

crops, stats = [], []
for p in PAGES:
    try:
        ex = LR.read_sheet_local(open(p, "rb").read())
    except Exception:                            # noqa: BLE001
        continue
    img = Image.open(p).convert("RGB")
    scale = float((ex.get("geometry") or {}).get("scale") or 1.0)
    st = ex["struct"]
    full = int(round(float(st.get("beats") or 4) * 8))
    for s in (st.get("systems") or []):
        per = collections.defaultdict(list)
        for n in (s.get("notes") or []):
            if not n.get("chord"):
                per[n.get("measure")].append(n)
        for _mi, ns in per.items():
            got = sum((DUR.get(n.get("duration"), 0) * 3 // 2)
                      if n.get("dotted") else DUR.get(n.get("duration"), 0)
                      for n in ns)
            gap = full - got
            if gap <= 0:
                continue
            for n in ns:
                d = n.get("duration")
                if d not in ORDER or n.get("rest") or "head" not in n:
                    continue
                i = ORDER.index(d)
                if i + 1 >= len(ORDER):
                    continue
                up = ORDER[i + 1]
                if (d, up) not in WANT:
                    continue
                delta = (DUR[up] - DUR[d]) * (3 if n.get("dotted") else 2) // 2
                if delta != gap:
                    continue
                h = n["head"]
                x, y = h["x"] / scale, h["y"] / scale
                w, hh = h["w"] / scale, h["h"] / scale
                # 머리 속 밝기 / 테두리 밝기 — 속이 비면 가운데가 밝다
                g = np.asarray(img.convert("L")).astype(float)
                y0, y1 = int(y + hh * .30), int(y + hh * .70)
                x0, x1 = int(x + w * .30), int(x + w * .70)
                core = g[y0:y1, x0:x1]
                edge = g[int(y):int(y + hh), int(x):int(x + w)]
                if core.size == 0 or edge.size == 0:
                    continue
                hollow = float(core.mean() - np.percentile(edge, 10))
                stats.append((hollow, d, up))
                pad = w * 1.1
                box = (int(x - pad), int(y - pad), int(x + w + pad), int(y + hh + pad))
                c = img.crop(box).resize(((box[2]-box[0])*6, (box[3]-box[1])*6),
                                         Image.LANCZOS)
                dr = ImageDraw.Draw(c)
                dr.rectangle([int(pad*6), int(pad*6),
                              int((pad+w)*6), int((pad+hh)*6)],
                             outline=(200, 40, 30), width=2)
                crops.append((hollow, f"{d[0]}→{up[0]}", c))

print(f"'한 단계 길게 읽어야' 하는 머리 {len(crops)}개")
if not crops:
    raise SystemExit
hs = sorted(h for h, *_ in stats)
print(f"속 비움 지표(가운데밝기 - 테두리잉크) — 중앙값 {hs[len(hs)//2]:.0f} · "
      f"25% {hs[len(hs)//4]:.0f} · 75% {hs[3*len(hs)//4]:.0f}")
print("  (0 에 가까우면 꽉 찬 머리 · 100 이상이면 속이 빈 머리)")
crops.sort(key=lambda t: -t[0])
cols, n = 6, min(len(crops), 24)
cw = max(c.width for _h, _l, c in crops[:n]); ch = max(c.height for _h, _l, c in crops[:n])
rows = (n + cols - 1) // cols
sheet = Image.new("RGB", (cols * cw, rows * (ch + 18)), "white")
dr = ImageDraw.Draw(sheet)
for i, (h, lab, c) in enumerate(crops[:n]):
    x, y = (i % cols) * cw, (i // cols) * (ch + 18)
    sheet.paste(c, (x, y)); dr.text((x + 3, y + ch + 3), f"{lab} {h:.0f}", fill=(20, 20, 20))
sheet.save("/tmp/head_eyes.png")
print("저장 /tmp/head_eyes.png", sheet.size)
