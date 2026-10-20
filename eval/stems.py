"""**기둥(stem)으로 음표 수를 센다 — LLM 없이.**

왜: 지금 LLM이 하는 일은 단별 음표·쉼표 개수를 세는 것뿐이고, 그게 장당
$0.094 의 전부다. 그런데 온음표를 뺀 모든 음표는 **기둥이 정확히 하나**다.
기둥은 오선을 지운 그림에서 세로로 긴 잉크 줄이라 모델 없이 셀 수 있다.

정답은 캐시된 LLM 개수(eval/counts). 여기서 맞으면 심판을 공짜로 바꿀 수 있다.

한계(미리 적어 둔다):
  · 화음은 기둥을 공유한다 → 적게 센다. 다만 실측상 화음 단은 4.6% 뿐이다.
  · 온음표는 기둥이 없다 → 따로 더해야 한다.
  · 줄막대도 세로줄이다 → 오선 높이를 꽉 채우는 것으로 가른다.
"""
import sys, os, json, glob, warnings
sys.path.insert(0, "tools")
warnings.filterwarnings("ignore")
import numpy as np
from PIL import Image
import probe as P, sheetcv as cv, layout as L, evaldet as E
from ultralytics import YOLO

# 기둥 모양 문턱 — 오선 간격(sp) 배수
MIN_H = 2.0      # 이보다 짧으면 기둥이 아니다 (가사 획·점 등)
MAX_W = 0.45     # 이보다 두꺼우면 줄막대·겹친 것
GAP = 0.5        # 이 안에 붙은 기둥은 하나로 본다


def stems_of(strict, st, sp, x_from=None, bars=()):
    """한 단에서 기둥 x 좌표 목록.

    x_from  : 이보다 왼쪽은 음자리표·조표·박자표라 센다는 의미가 없다
    bars    : 줄막대 x — 세로줄이라 기둥으로 세어진다
    """
    y0 = max(0, int(st.top - sp * 3.5))
    y1 = min(strict.shape[0], int(st.bottom + sp * 3.5))
    band = strict[y0:y1]
    if band.size == 0:
        return []
    h, w = band.shape
    ink = band > 0

    # 열마다 **가장 긴 세로 연속 잉크**와 그 구간
    best_len = np.zeros(w, dtype=np.int32)
    best_top = np.zeros(w, dtype=np.int32)
    cur = np.zeros(w, dtype=np.int32)
    cur_top = np.zeros(w, dtype=np.int32)
    for y in range(h):
        row = ink[y]
        cur_top = np.where(row & (cur == 0), y, cur_top)
        cur = np.where(row, cur + 1, 0)
        upd = cur > best_len
        best_len = np.where(upd, cur, best_len)
        best_top = np.where(upd, cur_top, best_top)

    staff_h = st.bottom - st.top
    cand = np.where(best_len >= sp * MIN_H)[0]
    keep = []
    for x in cand:
        top = y0 + best_top[x]
        bot = top + best_len[x]
        # **기둥은 반드시 오선과 겹친다.** 가사 세로획(ㅏ ㅣ ㅓ …)과 코드 글자는
        # 오선 밖에만 있으므로 이 한 줄로 거의 다 빠진다.
        if bot <= st.top or top >= st.bottom:
            continue
        # 예전엔 "오선 위아래를 다 덮으면 줄막대"로 걸렀는데, 오선 아래
        # 음표에서 위로 뻗은 **진짜 기둥**이 그 모양이라 통째로 지워졌다
        # (실측: day2sb-2 단3이 17개 중 4개만 남았다). 줄막대는 layout 이
        # 따로 주므로 여기서 모양으로 추측하지 않는다.
        if x_from is not None and x < x_from:
            continue                      # 음자리표·조표·박자표 구간
        if any(abs(x - b) <= sp * 0.7 for b in bars):
            continue                      # 줄막대·도돌이표
        keep.append(int(x))
    if not keep:
        return []

    # 붙어 있는 열은 한 기둥
    groups, run = [], [keep[0]]
    for x in keep[1:]:
        if x - run[-1] <= max(1, sp * GAP):
            run.append(x)
        else:
            groups.append(run); run = [x]
    groups.append(run)
    # 너무 두꺼운 덩어리는 기둥이 아니다
    return [int(np.mean(g)) for g in groups if len(g) <= max(2, sp * MAX_W)]


MODEL = None


def run(page):
    """검출기는 **무료**(로컬)다 — 돈이 드는 건 LLM 뿐이라 여기 써도 원가 0이다."""
    global MODEL
    if MODEL is None:
        MODEL = YOLO("models/omr.pt")
    big, _ = P.upscale(Image.open(page).convert("RGB"))
    ink, st = cv.find_staves_best(big.convert("L"))
    sp = cv.median_spacing(st)
    strict = cv.remove_staff_lines(ink, st, protect_noteheads=True)
    boxes, _m = E.detect_by_staff(MODEL, big, 0.50)
    out = []
    for s_ in st:
        mid = (s_.top + s_.bottom) / 2.0
        half = (s_.bottom - s_.top) * 1.4
        near = [b for b in boxes if abs(b["y"] + b["h"] / 2.0 - mid) < half]
        firsts = [b["x"] for b in near
                  if b["class"].startswith(("notehead", "rest"))]
        x_from = (min(firsts) - sp * 0.6) if firsts else None
        heads = [b for b in near if b["class"].startswith("notehead")]
        try:
            bars = L.barlines_of(strict, s_, sp, heads, x_from)
        except Exception:
            bars = []
        out.append(len(stems_of(strict, s_, sp, x_from, bars)))
    return out, sp


print(f"{'악보':16} {'단':>3} {'기둥':>5} {'LLM':>5} {'차':>5}")
tot_s = tot_l = 0; rows = []
for f in sorted(glob.glob("eval/counts/*.json")):
    name = os.path.basename(f)[:-5]
    img = f"악보샘플/이미지/{name}.png"
    if not os.path.exists(img):
        continue
    llm = [s["notes"] for s in json.load(open(f))["systems"]]
    try:
        stems, sp = run(img)
    except Exception as e:
        print(f"{name:16} 오류 {type(e).__name__}: {e}"[:80]); continue
    n = min(len(stems), len(llm))
    ds, dl = sum(stems[:n]), sum(llm[:n])
    tot_s += ds; tot_l += dl
    rows.append({"page": name, "stems": stems[:n], "llm": llm[:n]})
    print(f"{name:16} {n:3} {ds:5} {dl:5} {ds-dl:+5}")
json.dump(rows, open("eval/stems.json", "w"), ensure_ascii=False, indent=1)
print(f"\n합계 기둥 {tot_s} · LLM {tot_l} · 비 {tot_s/max(1,tot_l):.2f}")
per = [(abs(a-b), r["page"], i+1, a, b) for r in rows
       for i,(a,b) in enumerate(zip(r["stems"], r["llm"]))]
exact = sum(1 for d,*_ in per if d == 0)
near = sum(1 for d,*_ in per if d <= 2)
print(f"단 {len(per)}개 · 정확히 일치 {exact} ({exact*100//max(1,len(per))}%) "
      f"· ±2 안 {near} ({near*100//max(1,len(per))}%)")
print("\n가장 많이 틀린 단:")
for d, pg, i, a, b in sorted(per, reverse=True)[:8]:
    print(f"  {pg:16} 단{i:2}  기둥 {a:3} vs LLM {b:3}  ({a-b:+d})")
