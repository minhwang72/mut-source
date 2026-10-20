#!/usr/bin/env python3
"""
**학습 데이터에 펜·형광펜을 얹는다.**

실제 콘티는 손으로 고쳐 쓴다 — 빨간 펜이 빔을 가로지르고(day2sb-1), 보라색
동그라미가 쉼표를 지나가고(wish0809-7), 형광펜 띠가 세로줄을 덮는다(wish0830-6).
그런데 합성 학습 데이터는 전부 **회색(L)** 이라 검출기는 색 있는 표시를 한 번도
본 적이 없다. 실제 판독은 컬러로 들어가므로, 그 자리의 기호를 통째로 놓쳤다.

정답 상자는 바꾸지 않는다 — 표시에 일부 가려져도 인쇄된 기호는 '있다'고 배우게.
표시 자체는 상자가 없으니 '무시할 것'으로 배운다.

    python tools/penmarks.py data/yolo_comb data/yolo_pen --frac 0.5

표시를 얹지 않은 장은 원본으로의 심볼릭 링크라 디스크를 거의 쓰지 않는다.
"""
from __future__ import annotations

import argparse
import math
import os
import random
from pathlib import Path

PEN = [(214, 40, 40), (200, 30, 90), (40, 80, 200), (120, 50, 170),
       (30, 140, 70), (230, 120, 20)]                 # 빨강·자홍·파랑·보라·초록·주황
HIGHLIGHT = [(255, 240, 80), (120, 230, 240), (255, 160, 200), (170, 170, 170),
             (190, 240, 140)]                          # 노랑·청록·분홍·회색·연두


def _stroke(draw, rng, w, h, color, width):
    """펜 한 획 — 직선·곡선·동그라미·낙서 중 하나."""
    kind = rng.choice(["line", "curve", "circle", "scribble"])
    if kind == "line":
        pts = [(rng.uniform(0, w), rng.uniform(0, h)) for _ in range(2)]
    elif kind == "curve":
        x0, x1 = sorted(rng.uniform(0, w) for _ in range(2))
        y, amp = rng.uniform(0.2 * h, 0.8 * h), rng.uniform(0.1, 0.5) * h
        pts = [(x0 + (x1 - x0) * t / 20, y + amp * math.sin(math.pi * t / 20))
               for t in range(21)]
    elif kind == "circle":
        cx, cy = rng.uniform(0, w), rng.uniform(0, h)
        r = rng.uniform(0.25, 0.9) * h
        pts = [(cx + r * 1.3 * math.cos(a / 20 * 2 * math.pi),
                cy + r * math.sin(a / 20 * 2 * math.pi)) for a in range(21)]
    else:
        x, y = rng.uniform(0, w), rng.uniform(0, h)
        pts = [(x, y)]
        for _ in range(rng.randint(4, 10)):
            x += rng.uniform(-0.15, 0.15) * h + rng.uniform(0, 0.12) * h
            y += rng.uniform(-0.3, 0.3) * h
            pts.append((x, y))
    draw.line(pts, fill=color + (rng.randint(190, 255),), width=width, joint="curve")


def mark(img, rng: random.Random):
    """회색 띠 이미지 한 장에 펜·형광펜을 얹어 RGB 로 돌려준다."""
    from PIL import Image, ImageDraw
    base = img.convert("RGB")
    w, h = base.size
    # 형광펜은 잉크 **아래**에 깔린다 — 곱하기 합성이라 검은 잉크는 그대로 검다
    if rng.random() < 0.6:
        tint = Image.new("RGB", (w, h), (255, 255, 255))
        d = ImageDraw.Draw(tint)
        for _ in range(rng.randint(1, 3)):
            col = rng.choice(HIGHLIGHT)
            if rng.random() < 0.5:                    # 세로 띠(세로줄·박 표시)
                x = rng.uniform(0, w); bw = rng.uniform(0.15, 0.5) * h
                d.rectangle([x, 0, x + bw, h], fill=col)
            else:                                     # 가로 상자(코드·가사 강조)
                x0 = rng.uniform(0, w * 0.8); x1 = x0 + rng.uniform(0.1, 0.5) * w
                y0 = rng.uniform(0, h * 0.6); y1 = y0 + rng.uniform(0.15, 0.5) * h
                d.rounded_rectangle([x0, y0, x1, y1], radius=h * 0.1, fill=col)
        from PIL import ImageChops
        base = ImageChops.multiply(base, tint)
    # 펜은 잉크 **위**에 — 빔·쉼표를 실제로 가린다
    if rng.random() < 0.8:
        over = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(over)
        width = max(1, int(round(rng.uniform(0.02, 0.06) * h)))
        col = rng.choice(PEN)
        for _ in range(rng.randint(1, 3)):
            _stroke(d, rng, w, h, col, width)
        base = Image.alpha_composite(base.convert("RGBA"), over).convert("RGB")
    return base


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("src"); ap.add_argument("dst")
    ap.add_argument("--frac", type=float, default=0.5)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    from PIL import Image
    src, dst = Path(a.src).resolve(), Path(a.dst).resolve()
    rng = random.Random(a.seed)
    n = m = 0
    for split in ("train", "val"):
        (dst / "images" / split).mkdir(parents=True, exist_ok=True)
        (dst / "labels" / split).mkdir(parents=True, exist_ok=True)
        for f in sorted((src / "images" / split).glob("*.png")):
            lab = src / "labels" / split / (f.stem + ".txt")
            out_l = dst / "labels" / split / lab.name
            if not out_l.exists():
                os.symlink(os.path.realpath(lab), out_l)
            out = dst / "images" / split / f.name
            n += 1
            if out.exists() or out.is_symlink():
                continue
            # 검증셋은 손대지 않는다 — 이전 모델들과 같은 잣대로 비교하려고
            if split == "train" and rng.random() < a.frac:
                mark(Image.open(f), rng).save(out)
                m += 1
            else:
                os.symlink(os.path.realpath(f), out)
    y = (src / "data.yaml").read_text().splitlines()
    (dst / "data.yaml").write_text("\n".join(
        f"path: {dst}" if l.startswith("path:") else l for l in y) + "\n")
    print(f"{n}장 중 {m}장에 펜·형광펜을 얹었다 → {dst}")


if __name__ == "__main__":
    main()
