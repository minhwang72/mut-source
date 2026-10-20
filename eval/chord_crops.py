"""mark_chords 가 묶은 자리를 **그대로 잘라 본다.**

숫자로는 "화음 장 4개가 나빠졌다"까지만 보인다. 그게 진짜 2성부인지
다른 것인지는 그림을 봐야 안다.
"""
import sys, os, warnings
sys.path.insert(0, "tools")
warnings.filterwarnings("ignore")
from PIL import Image, ImageDraw
import numpy as np
import probe as P, sheetcv as cv, evaldet as E, durations as D, detstruct as DS
from ultralytics import YOLO

SAMPLE = os.path.expanduser("악보샘플/이미지")
OUT = "/tmp/chordcrops"
os.makedirs(OUT, exist_ok=True)
pages = sys.argv[1:] or ["day2conti-3", "wish0809-4", "day2sb-6", "set0802-7",
                         "camp0814b-07", "set0802-3"]
M = YOLO("runs/detect/runs/omr_marks/weights/best.pt")

for page in pages:
    big, _ = P.upscale(Image.open(f"{SAMPLE}/{page}.png").convert("RGB"))
    gray = np.asarray(big.convert("L")).astype("float32")
    ink, st = cv.find_staves_best(big.convert("L"))
    sp = cv.median_spacing(st)
    boxes, _ = E.detect_guided(M, big, [0] * len(st))
    mids = [(s.top + s.bottom) / 2.0 for s in st]
    bysys = [[] for _ in st]
    for b in boxes:
        cy = b["y"] + b["h"] / 2.0
        bysys[min(range(len(mids)), key=lambda i: abs(mids[i] - cy))].append(b)

    n = 0
    for si, (grp, s_) in enumerate(zip(bysys, st)):
        grp[:] = D.fix_rest_class(grp, s_.top, sp)
        got = D.read_durations(grp, sp, gray=gray)
        DS.mark_chords(got, sp)
        for i, b in enumerate(got):
            if not b.get("chord"):
                continue
            a = got[i - 1]
            x0 = int(min(a["x"], b["x"]) - sp * 4); x1 = int(max(a["x"]+a["w"], b["x"]+b["w"]) + sp * 4)
            y0 = int(min(a["y"], b["y"]) - sp * 4); y1 = int(max(a["y"]+a["h"], b["y"]+b["h"]) + sp * 4)
            crop = big.crop((max(0,x0), max(0,y0), x1, y1)).resize(
                ((x1-max(0,x0))*2, (y1-max(0,y0))*2), Image.LANCZOS)
            d = ImageDraw.Draw(crop)
            for h, col in ((a, (0,140,255)), (b, (230,0,0))):
                d.rectangle([(h["x"]-max(0,x0))*2, (h["y"]-max(0,y0))*2,
                             (h["x"]+h["w"]-max(0,x0))*2, (h["y"]+h["h"]-max(0,y0))*2],
                            outline=col, width=2)
            crop.save(f"{OUT}/{page}_단{si+1}_{n:02d}.png")
            n += 1
    print(f"{page}: 묶인 쌍 {n}개")
print("→", OUT)
