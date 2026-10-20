"""판독 한 장이 어디서 시간을 쓰는가. 100초가 어디로 가는지 모르면 못 줄인다."""
import sys, os, time, warnings, json
sys.path.insert(0,"tools"); sys.path.insert(0,"server"); warnings.filterwarnings("ignore")
import numpy as np
from PIL import Image
import prepare, detect_chords, read_chords, sheetcv as cv, evaldet as E, detstruct as DS
from ultralytics import YOLO

path = sys.argv[1] if len(sys.argv) > 1 else "악보샘플/이미지/wish0809-4.png"
T = {}
def tick(k, t0): T[k] = time.time() - t0; return time.time()

t = time.time()
img = prepare.load(open(path, "rb")); t = tick("① 열기", t)
rep, img, ink, staves = prepare.analyze_image(img); t = tick("② 전처리·오선", t)
detect = detect_chords.detect_from_ink(img, ink, staves); t = tick("③ 코드 상자", t)
boxes = read_chords.flatten_boxes(detect)
collage, n = read_chords.build_collage(img, boxes); t = tick("④ 콜라주", t)
reads = read_chords.read(collage, n); t = tick("⑤ 코드 LLM", t)

sp = cv.median_spacing(staves)
M = YOLO("models/omr.pt"); t = tick("⑥ 모델 로드", t)
import readcounts as RC
counts_raw = RC.read_page(Image.open(path).convert("RGB")); t = tick("⑦ 개수 LLM", t)
rows = (counts_raw.get("systems") if isinstance(counts_raw, dict) else counts_raw) or []
counts = [{"notes": int((rows[i] if i < len(rows) else {}).get("notes") or 0),
           "rests": int((rows[i] if i < len(rows) else {}).get("rests") or 0), "marks": []}
          for i in range(len(staves))]
ex, exr = DS.expects(counts)
boxes2, meta = E.detect_guided(M, img, ex, expect_rests=exr); t = tick("⑧ 머리 검출", t)
curves = DS.detect_curves(img, "models/omr_tie.pt", ex, exr); t = tick("⑨ 이음줄 검출", t)
strict = cv.remove_staff_lines(ink, staves, protect_noteheads=True); t = tick("⑩ 오선 제거", t)
gray = np.asarray(img.convert("L")).astype("float32")
struct = DS.build_from(boxes2, staves, strict, sp, gray, counts, curves=curves, meta=meta)
t = tick("⑪ 구조 조립", t)

tot = sum(T.values())
print(f"\n=== {os.path.basename(path)} · 오선 {len(staves)}단 · 합계 {tot:.1f}초")
for k, v in sorted(T.items(), key=lambda kv: -kv[1]):
    print(f"  {k:14s} {v:6.2f}초  {v/tot*100:4.1f}%")
