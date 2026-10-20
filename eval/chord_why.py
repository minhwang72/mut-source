"""화음 지원으로 **상태가 바뀐 마디**만 뽑아 본다.

"묶은 게 틀렸다"와 "묶은 건 맞는데 다른 데서 어긋난다"는 전혀 다른 문제다.
마디별 음가 합을 화음 제외 전/후로 나란히 찍어 어느 쪽인지 가른다.
"""
import sys, os, warnings
sys.path.insert(0, "tools")
warnings.filterwarnings("ignore")
from PIL import Image
import numpy as np
import probe as P, sheetcv as cv, evaldet as E, durations as D, detstruct as DS
from ultralytics import YOLO

SAMPLE = os.path.expanduser("악보샘플/이미지")
VAL = {"whole":4.0,"half":2.0,"quarter":1.0,"eighth":0.5,"16th":0.25,"32nd":0.125}
def val(d, dot): return VAL[d] * (1.5 if dot else 1.0)

M = YOLO("runs/detect/runs/omr_marks/weights/best.pt")
for page in sys.argv[1:]:
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

    print(f"\n=== {page}")
    for si, (grp, s_) in enumerate(zip(bysys, st)):
        grp[:] = D.fix_rest_class(grp, s_.top, sp)
        got = D.read_durations(grp, sp, gray=gray)
        nch = DS.mark_chords(got, sp)
        if not nch:
            continue
        before = sum(val(n["duration"], n.get("dotted")) for n in got)
        after  = sum(val(n["duration"], n.get("dotted")) for n in got if not n.get("chord"))
        print(f"  단{si+1}: 머리 {len(got)} · 묶임 {nch} · 합 {before:.2f} → {after:.2f}")
