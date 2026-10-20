"""**학습으로 LLM을 걷어낼 수 있는가**를 가르는 측정.

검출기가 음표를 놓치는 이유가 둘 중 무엇인지가 전부다:
  ① 낮은 점수로는 **보고 있다** → 순위·문턱 문제 → 학습으로 고칠 수 있다
  ② 낮은 점수에도 **후보조차 없다** → 아예 못 본다 → 훨씬 어렵다

문턱 0.50(지금 쓰는 값)과 0.05(거의 다 받는 값)에서 후보 수를 세어
LLM 정답과 비교한다.
"""
import sys, os, json, glob, warnings
sys.path.insert(0, "tools")
warnings.filterwarnings("ignore")
from PIL import Image
import probe as P, sheetcv as cv, evaldet as E
from ultralytics import YOLO

M = YOLO("models/omr.pt")
TARGET = E.INPUT_SPACING


def counts_at(big, st, sp, conf):
    """단별 (중복 제거한) 머리 후보 수."""
    out = []
    for s_ in st:
        y0 = max(0, int(s_.top - sp * 5)); y1 = min(big.height, int(s_.bottom + sp * 6))
        strip = big.crop((0, y0, big.width, y1))
        need = int(strip.width * (TARGET / sp)); size = 32 * max(1, round(need / 32))
        r = M.predict(strip, imgsz=size, conf=conf, verbose=False)[0]
        hs = sorted(((b[0] + (b[2]-b[0])/2, b[1] + y0 + (b[3]-b[1])/2, float(c))
                     for b, cl, c in zip(r.boxes.xyxy.tolist(), r.boxes.cls.tolist(),
                                         r.boxes.conf.tolist())
                     if r.names[int(cl)].startswith("notehead")),
                    key=lambda t: -t[2])
        kept = []
        for cx, cy, _c in hs:
            if any(abs(cx-kx) < sp*0.5 and abs(cy-ky) < sp*0.5 for kx, ky, _ in kept):
                continue
            kept.append((cx, cy, _c))
        out.append(len(kept))
    return out


rows = []
for f in sorted(glob.glob("eval/counts/*.json")):
    name = os.path.basename(f)[:-5]
    img = f"악보샘플/이미지/{name}.png"
    if not os.path.exists(img):
        continue
    llm = [s["notes"] for s in json.load(open(f))["systems"]]
    big, _ = P.upscale(Image.open(img).convert("RGB"))
    ink, st = cv.find_staves_best(big.convert("L"))
    sp = cv.median_spacing(st)
    hi = counts_at(big, st, sp, 0.50)
    lo = counts_at(big, st, sp, 0.05)
    for i in range(min(len(st), len(llm))):
        rows.append({"page": name, "sys": i, "hi": hi[i], "lo": lo[i], "llm": llm[i]})
    print(name, flush=True)

json.dump(rows, open("eval/recall_headroom.json", "w"), ensure_ascii=False, indent=1)
n = len(rows)
print(f"\n단 {n}개")
hi_ok = sum(1 for r in rows if r["hi"] == r["llm"])
lo_enough = sum(1 for r in rows if r["lo"] >= r["llm"])
lo_exact = sum(1 for r in rows if r["lo"] == r["llm"])
print(f"  문턱 0.50 에서 개수가 정답과 같은 단     {hi_ok:3}/{n} ({hi_ok/n:.0%})")
print(f"  문턱 0.05 에서 후보가 정답 **이상**인 단  {lo_enough:3}/{n} ({lo_enough/n:.0%})  ← 보고는 있다")
print(f"  문턱 0.05 에서 개수가 정답과 같은 단     {lo_exact:3}/{n} ({lo_exact/n:.0%})")
miss = [r for r in rows if r["lo"] < r["llm"]]
print(f"\n후보조차 모자란 단 {len(miss)}개 (아예 못 본 것):")
for r in sorted(miss, key=lambda r: r["lo"]-r["llm"])[:8]:
    print(f"  {r['page']:14} 단{r['sys']+1:2}  0.05후보 {r['lo']:3} < 정답 {r['llm']:3}  ({r['lo']-r['llm']:+d})")
over = [r["lo"] - r["llm"] for r in rows if r["lo"] >= r["llm"]]
if over:
    import statistics
    print(f"\n보고 있는 단의 군더더기 후보: 중앙값 {statistics.median(over):.0f}개 "
          f"(이만큼을 점수로 걸러내야 한다)")
