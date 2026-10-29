#!/usr/bin/env python3
"""
**마디 단위 학습 그림을 판독 때와 같은 크기로 모은다.**

label_build.py 의 마디 그림은 폭 100~200px 이라, 그대로 학습시키면 학습기가 긴 변을
960 으로 키워 오선 간격이 판독 때(6.5px)의 몇 배가 된다. 그래서 흰 바탕(960×960)에
원래 크기로 줄지어 붙인다. 바탕마다 마디를 무작위로 뽑으므로 n 장을 만들면 자연히
여러 번 쓰인다(적은 라벨 보강).

    .venv/bin/python eval/pack_crops.py data/real_ai data/real_ai_packed 60
"""
from __future__ import annotations

import glob
import os
import random
import sys

SIZE = 960
GAP = 8


def main(src: str, out: str, n: int) -> None:
    from PIL import Image
    os.makedirs(f"{out}/images/train", exist_ok=True)
    os.makedirs(f"{out}/labels/train", exist_ok=True)
    items = []
    for p in sorted(glob.glob(f"{src}/images/train/*.png")):
        k = os.path.basename(p)[:-4]
        boxes = [l.split() for l in open(f"{src}/labels/train/{k}.txt") if l.strip()]
        items.append((Image.open(p).convert("L"), boxes))
    rnd = random.Random(0)
    for i in range(n):
        canvas = Image.new("L", (SIZE, SIZE), 255)
        lines, x, y, row_h = [], GAP, GAP, 0
        for im, boxes in rnd.sample(items, len(items)):
            w, h = im.size
            if x + w > SIZE:
                x, y, row_h = GAP, y + row_h + GAP, 0
            if y + h > SIZE:
                break
            canvas.paste(im, (x, y))
            for c, cx, cy, bw, bh in boxes:
                lines.append(f"{c} {(x + float(cx) * w) / SIZE:.6f} {(y + float(cy) * h) / SIZE:.6f} "
                             f"{float(bw) * w / SIZE:.6f} {float(bh) * h / SIZE:.6f}")
            x += w + GAP
            row_h = max(row_h, h)
        canvas.save(f"{out}/images/train/pack{i:03d}.png")
        open(f"{out}/labels/train/pack{i:03d}.txt", "w").write("\n".join(lines) + "\n")
    print(f"{n}장 · 마디 {len(items)}개")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]))
