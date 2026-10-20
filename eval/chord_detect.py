"""화음 단에서 **같은 x에 쌓인 머리**를 각 모델이 얼마나 보는가.

화음 지원의 전제: 쌓인 머리를 검출해야 묶을 수 있다. 못 보면 묶을 것이 없다.
정답은 눈으로 판정한 화음 단 목록이다.
"""
import sys, os, warnings
sys.path.insert(0, "tools")
warnings.filterwarnings("ignore")
from PIL import Image
import probe as P, sheetcv as cv, evaldet as E
from ultralytics import YOLO

SAMPLE = os.path.expanduser("악보샘플/이미지")
POS = {"camp0814b-06": {0, 2}, "camp0814b-07": {4}, "set0802-3": {0, 8},
       "set0802-4": {4}, "set0816-3": {0}, "set0816-4": {4},
       "day2conti-3": {1}, "day2sb-2": {1}, "day2sb-6": {1},
       "wish0809-4": {1, 2}, "set0802-7": {0}}
MODELS = {"옛": "models/omr.pt", "새": "runs/detect/runs/omr_marks/weights/best.pt"}


def stacks(M, page, conf=0.25):
    big, _ = P.upscale(Image.open(f"{SAMPLE}/{page}.png").convert("RGB"))
    ink, st = cv.find_staves_best(big.convert("L"))
    sp = cv.median_spacing(st)
    out = []
    for s_ in st:
        y0 = max(0, int(s_.top - sp * 5)); y1 = min(big.height, int(s_.bottom + sp * 6))
        strip = big.crop((0, y0, big.width, y1))
        need = int(strip.width * (E.INPUT_SPACING / sp)); size = 32 * max(1, round(need / 32))
        r = M.predict(strip, imgsz=size, conf=conf, verbose=False)[0]
        hs = sorted(((b[0]+(b[2]-b[0])/2, b[1]+y0+(b[3]-b[1])/2, float(c))
                     for b, cl, c in zip(r.boxes.xyxy.tolist(), r.boxes.cls.tolist(),
                                         r.boxes.conf.tolist())
                     if r.names[int(cl)].startswith("notehead")), key=lambda t: -t[2])
        kept = []
        for cx, cy, c in hs:
            if any(abs(cx-kx) < sp*0.5 and abs(cy-ky) < sp*0.5 for kx, ky, _ in kept):
                continue
            kept.append((cx, cy, c))
        kept.sort()
        cols = []
        for cx, cy, c in kept:
            if cols and abs(cx - cols[-1][-1][0]) < sp * 0.6:
                cols[-1].append((cx, cy))
            else:
                cols.append([(cx, cy)])
        # 같은 기둥이라도 **세로로 떨어져야** 화음이다
        deep = sum(1 for g in cols
                   if len(g) >= 2 and max(p[1] for p in g) - min(p[1] for p in g) > sp * 0.8)
        out.append((len(cols), deep, len(kept)))
    return out


print(f"{'장':14} {'단':>3} {'정답':>4} | {'옛 기둥/쌓임':>12} | {'새 기둥/쌓임':>12}")
tot = {"옛": [0, 0], "새": [0, 0]}
for pg, pos in POS.items():
    res = {}
    for tag, w in MODELS.items():
        res[tag] = stacks(YOLO(w), pg)
    for i in range(min(len(res["옛"]), len(res["새"]))):
        y = 1 if i in pos else 0
        if not y:
            continue
        a, b = res["옛"][i], res["새"][i]
        tot["옛"][0] += a[1]; tot["새"][0] += b[1]
        print(f"{pg:14} {i+1:3} {y:4} | {a[0]:5}/{a[1]:<6} | {b[0]:5}/{b[1]:<6}")
print(f"\n화음 단에서 검출한 '쌓인 기둥' 합계 — 옛 {tot['옛'][0]} · 새 {tot['새'][0]}")
