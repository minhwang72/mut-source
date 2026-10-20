"""**기둥을 대체재가 아니라 교차검증으로 쓴다.**

기둥만으로 개수를 맞히는 건 실패했다(단별 정확 9%). 하지만 질문을 바꾸면
쓸모가 있다: "검출기 개수와 기둥 개수가 같으면, 그 단은 LLM에 안 물어도
되는가?" 맞다면 그 비율만큼 원가가 그냥 줄어든다.

정밀도(맞다고 봤을 때 실제로 맞은 비율)가 핵심이다 — 틀린 단을 건너뛰면
그 단이 통째로 깨진다.
"""
import sys, os, json, glob, warnings
sys.path.insert(0, "tools"); sys.path.insert(0, "eval")
warnings.filterwarnings("ignore")
from PIL import Image
from stems import stems_of
import probe as P, sheetcv as cv, layout as L, evaldet as E
from ultralytics import YOLO

M = YOLO("models/omr.pt")
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
    strict = cv.remove_staff_lines(ink, st, protect_noteheads=True)
    boxes, _m = E.detect_by_staff(M, big, 0.50)
    for i, s_ in enumerate(st):
        if i >= len(llm):
            break
        mid = (s_.top + s_.bottom) / 2.0
        half = (s_.bottom - s_.top) * 1.4
        near = [b for b in boxes if abs(b["y"] + b["h"] / 2.0 - mid) < half]
        det = sum(1 for b in near if b["class"].startswith("notehead"))
        firsts = [b["x"] for b in near if b["class"].startswith(("notehead", "rest"))]
        x_from = (min(firsts) - sp * 0.6) if firsts else None
        heads = [b for b in near if b["class"].startswith("notehead")]
        try:
            bars = L.barlines_of(strict, s_, sp, heads, x_from)
        except Exception:
            bars = []
        stem = len(stems_of(strict, s_, sp, x_from, bars))
        rows.append({"page": name, "sys": i, "det": det, "stem": stem, "llm": llm[i]})
    print(name, flush=True)

json.dump(rows, open("eval/stems_gate.json", "w"), ensure_ascii=False, indent=1)
print(f"\n단 {len(rows)}개")
for tol in (0, 1, 2):
    agree = [r for r in rows if abs(r["det"] - r["stem"]) <= tol]
    right = [r for r in agree if r["det"] == r["llm"]]
    skip = len(agree) / max(1, len(rows))
    prec = len(right) / max(1, len(agree))
    print(f"  검출≈기둥 ±{tol}: 건너뛸 단 {len(agree):3} ({skip:4.0%}) · "
          f"그중 실제로 맞음 {len(right):3} → 정밀도 {prec:4.0%}")
base = sum(1 for r in rows if r["det"] == r["llm"])
print(f"\n참고: 검출기 개수가 LLM과 같은 단 {base}/{len(rows)} ({base/len(rows):.0%})")
