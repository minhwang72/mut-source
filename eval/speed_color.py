"""색 필터가 판독을 얼마나 느리게 하는가. 켠 것과 끈 것을 **같은 장에서 번갈아** 잰다."""
import sys, os, time, warnings, statistics as S
sys.path.insert(0, "tools")
warnings.filterwarnings("ignore")
from PIL import Image
import probe as P, evaldet as E, detstruct as DS, sheetcv as cv
from ultralytics import YOLO
import json

M = YOLO("models/omr.pt")
PAGES = ["camp0814b-07", "day2sb-2", "set0802-5", "wish0823-3"]
on, off = [], []
for pg in PAGES:
    big, _ = P.upscale(Image.open(f"악보샘플/이미지/{pg}.png").convert("RGB"))
    counts = json.load(open(f"eval/counts/{pg}.json"))["systems"]
    ex, exr = DS.expects(counts)
    M.predict(big.convert("L"), imgsz=960, conf=0.5, verbose=False)   # 예열
    for label, abs_th in (("on", 0.80), ("off", 99.0)):   # 99 면 절대 안 걸림
        E.COLOR_ABS = abs_th
        t0 = time.perf_counter()
        E.detect_guided(M, big, ex, expect_rests=exr)
        dt = time.perf_counter() - t0
        (on if label == "on" else off).append(dt)
    print(f"{pg:14} 켬 {on[-1]:6.2f}s · 끔 {off[-1]:6.2f}s · 차이 {on[-1]-off[-1]:+.2f}s", flush=True)
E.COLOR_ABS = 0.80
print(f"\n평균  켬 {S.mean(on):.2f}s · 끔 {S.mean(off):.2f}s "
      f"· 추가 {S.mean(on)-S.mean(off):+.2f}s ({(S.mean(on)/S.mean(off)-1):+.1%})")
