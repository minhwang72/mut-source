"""**유채색 오검출을 색으로 거른다 — 학습 없이.**

크롭 103개를 눈으로 보니 오검출이 거의 전부 유채색이었다: 빨강·주황 구역
표시 상자(A B C D E), 파랑·빨강 손글씨, 청록 형광펜. 진짜 음표는 검정이다.

그런데 파이프라인은 검출 직전에 _gray() 로 색을 버린다. 빨간 A 가 회색조가
되면 검은 머리와 구분이 안 된다 — 검출기 탓이 아니라 정보를 버린 탓이다.

여기서는 **원본 컬러**에서 머리 상자의 채도를 재서, 유채색이면 음표가
아니라고 본다. 진짜 머리는 잉크라 채도가 낮다.
"""
import sys, os, json, glob, warnings
sys.path.insert(0, "tools")
warnings.filterwarnings("ignore")
import numpy as np
from PIL import Image
import probe as P, sheetcv as cv, evaldet as E
from ultralytics import YOLO

M = YOLO(sys.argv[1] if len(sys.argv) > 1 else "models/omr.pt")
TARGET = E.INPUT_SPACING


def sat_of(rgb, b):
    """상자 안에서 **어두운 화소들**의 채도 중앙값. 배경(흰색)은 뺀다."""
    x0, y0 = max(0, int(b[0])), max(0, int(b[1]))
    x1, y1 = int(b[2]), int(b[3])
    patch = rgb[y0:y1, x0:x1].astype("float32")
    if patch.size == 0:
        return 0.0
    mx = patch.max(axis=2)
    mn = patch.min(axis=2)
    ink = mx < 200                      # 잉크로 볼 만큼 어두운 화소
    if ink.sum() < 4:
        return 0.0
    # HSV 채도: (max-min)/max
    s = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0.0)
    return float(np.median(s[ink]))


rows = []
for f in sorted(glob.glob("eval/counts/*.json")):
    name = os.path.basename(f)[:-5]
    img = f"악보샘플/이미지/{name}.png"
    if not os.path.exists(img):
        continue
    llm = [s["notes"] for s in json.load(open(f))["systems"]]
    big, _ = P.upscale(Image.open(img).convert("RGB"))
    rgb = np.asarray(big)
    ink, st = cv.find_staves_best(big.convert("L"))
    sp = cv.median_spacing(st)
    for i, s_ in enumerate(st):
        if i >= len(llm):
            break
        y0 = max(0, int(s_.top - sp * 5)); y1 = min(big.height, int(s_.bottom + sp * 6))
        strip = big.crop((0, y0, big.width, y1))
        need = int(strip.width * (TARGET / sp)); size = 32 * max(1, round(need / 32))
        r = M.predict(strip, imgsz=size, conf=0.05, verbose=False)[0]
        hs = sorted(((b[0], b[1] + y0, b[2], b[3] + y0, float(c))
                     for b, cl, c in zip(r.boxes.xyxy.tolist(), r.boxes.cls.tolist(),
                                         r.boxes.conf.tolist())
                     if r.names[int(cl)].startswith("notehead")),
                    key=lambda t: -t[4])
        kept = []
        for box in hs:
            cx, cy = (box[0]+box[2])/2, (box[1]+box[3])/2
            if any(abs(cx-(k[0]+k[2])/2) < sp*0.5 and abs(cy-(k[1]+k[3])/2) < sp*0.5
                   for k in kept):
                continue
            kept.append(box)
        n = llm[i]
        for j, box in enumerate(kept):
            rows.append({"page": name, "sys": i, "rank": j, "conf": box[4],
                         "sat": sat_of(rgb, box),
                         # 정답 개수 안쪽이면 진짜로 본다(근사)
                         "real": j < n})
    print(name, flush=True)

json.dump(rows, open("eval/color_filter.json", "w"), ensure_ascii=False)
real = [r["sat"] for r in rows if r["real"]]
fake = [r["sat"] for r in rows if not r["real"]]
import statistics as S
print(f"\n=== 머리 {len(rows)}개 (진짜 근사 {len(real)} · 용의자 {len(fake)})")
print(f"  진짜  채도 중앙값 {S.median(real):.3f} · 상위5% {sorted(real)[int(len(real)*0.95)]:.3f}")
print(f"  용의자 채도 중앙값 {S.median(fake):.3f} · 상위25% {sorted(fake)[int(len(fake)*0.75)]:.3f}")
print("\n문턱별 — 이 값을 넘으면 '유채색이라 음표 아님'으로 버림")
print(f"{'문턱':>6} {'진짜 잃음':>10} {'용의자 걸러냄':>14}")
for t in (0.15, 0.20, 0.25, 0.30, 0.40, 0.50):
    lost = sum(1 for s in real if s >= t)
    cut = sum(1 for s in fake if s >= t)
    print(f"{t:6.2f} {lost:6}/{len(real)} ({lost/len(real):4.1%}) {cut:6}/{len(fake)} ({cut/len(fake):5.1%})")
