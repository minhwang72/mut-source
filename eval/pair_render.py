#!/usr/bin/env python3
"""
**점검 그림 — 단마다 원본(위)과 결과(아래)를 붙인다.** 노란 마디는 결과 쪽에 칠해져 있다.

eval/devserve.py 로 띄운 화면이 eval/logs/render/<장>.png(결과 캔버스, 노란 칠)와
<장>.json(마디 상자)을 남긴 뒤에 돌린다. 출력: eval/logs/render/pairs/<장>_s<단>.png
저작물이라 저장소 밖(eval/logs)에만 둔다.

    .venv/bin/python eval/pair_render.py eval/sweep_hb_c2_structs 악보샘플/학습용_이미지 t009-3 ...
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

SDIR, IMG = Path(sys.argv[1]), Path(sys.argv[2])
R = Path("eval/logs/render")
(R / "pairs").mkdir(parents=True, exist_ok=True)
for page in sys.argv[3:]:
    d = json.loads((SDIR / f"{page}.json").read_text())
    geo = d["ex"]["geometry"]
    k = float(geo.get("scale") or 1)
    orig = Image.open(IMG / f"{page}.png").convert("RGB")
    out = Image.open(R / f"{page}.png").convert("RGB")
    meta = json.loads((R / f"{page}.json").read_text())
    tops = {}
    for b in meta["boxes"]:
        si = b["src"][0]
        tops[si] = min(tops.get(si, 1e9), b["y"])
    sysl = geo["systems"]
    for si, s in enumerate(sysl):
        sp = s["spacing"]
        y0 = max(0, (s["staffTop"] - sp * 5) / k)
        nxt = sysl[si + 1]["staffTop"] - sp * 4.5 if si + 1 < len(sysl) else s["staffBottom"] + sp * 9
        y1 = min(orig.height, nxt / k)
        a = orig.crop((0, int(y0), orig.width, int(y1)))
        if si not in tops:
            continue
        ry0 = max(0, int(tops[si] - 10))
        later = [t for j, t in tops.items() if j > si]
        ry1 = int(min(later) - 10) if later else out.height
        b = out.crop((0, ry0, out.width, max(ry0 + 10, ry1)))
        b = b.resize((a.width, max(1, round(b.height * a.width / b.width))))
        pair = Image.new("RGB", (a.width, a.height + b.height + 28), "white")
        pair.paste(a, (0, 0))
        dr = ImageDraw.Draw(pair)
        dr.rectangle((0, a.height, a.width, a.height + 28), fill=(40, 40, 40))
        dr.text((10, a.height + 8), f"{page}  system {si + 1}   TOP = original   BOTTOM = our output (yellow = flagged for user check)", fill="white")
        pair.paste(b, (0, a.height + 28))
        pair.save(R / "pairs" / f"{page}_s{si + 1}.png")
    print(page, len(sysl), flush=True)
