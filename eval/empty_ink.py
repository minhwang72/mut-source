"""
**빈 마디 자리에 잉크가 있나.**

줄막대 사이에 음표가 하나도 없는 마디가 25장에 24개 있다. 둘 중 하나다.
  · 줄막대 헛검출 — 그 구간은 사실 빈 종이다. 지우면 된다
  · 온쉼표 등을 못 읽음 — 잉크가 있다. 지우면 박자가 밀린다

화소로 가른다. 그 마디의 x 구간에서 오선 띠 안의 잉크 비율을 재고,
같은 단의 **음표가 있는 마디**와 견준다. 비어 있으면 헛검출이다.
"""
import os, sys, warnings, collections
sys.path.insert(0, "tools"); sys.path.insert(0, "server")
warnings.filterwarnings("ignore")
exec(open("eval/ai_tally.py").read().split("calls = install_cache()")[0])
install_cache()
import numpy as np
import serve
import sheetcv as cv
from PIL import Image

PAGES = sorted(f"악보샘플/이미지/{f}" for f in os.listdir("악보샘플/이미지")
               if f.endswith(".png"))
PAGES = PAGES[::max(1, len(PAGES) // 25)][:25]
serve.STATE["mode"] = "ai"

rows = []
for p in PAGES:
    name = os.path.basename(p)[:-4]
    try:
        ex = serve.read_sheet(open(p, "rb").read(), None)
    except Exception:                            # noqa: BLE001
        continue
    st = ex.get("struct") or {}
    geo = ex.get("geometry") or {}
    gsys = geo.get("systems") or []
    scale = float(geo.get("scale") or 1.0)
    img = Image.open(p).convert("L")
    g = np.asarray(img).astype(float)
    for si, s in enumerate(st.get("systems") or []):
        if si >= len(gsys):
            continue
        gs = gsys[si] or {}
        bars = gs.get("bars")
        if not bars:
            continue
        per = collections.defaultdict(list)
        for n in (s.get("notes") or []):
            per[n.get("measure")].append(n)
        total = s.get("measures") or 0
        # 마디 경계: 왼쪽끝 + bars + 오른쪽끝
        left = float(gs.get("left", 0)) / scale
        right = float(gs.get("right", img.width * scale)) / scale
        xs = [left] + [b / scale for b in bars] + [right]
        if len(xs) - 1 != total:
            continue                             # 경계 수가 안 맞으면 건너뛴다
        top = float(gs.get("staffTop", 0)) / scale
        bot = float(gs.get("staffBottom", 0)) / scale
        if bot <= top:
            continue
        pad = (bot - top) * 0.6
        y0, y1 = int(max(0, top - pad)), int(min(g.shape[0], bot + pad))
        dens = []
        for mi in range(1, total + 1):
            a, b = int(xs[mi - 1]), int(xs[mi])
            if b - a < 4:
                dens.append(None); continue
            box = g[y0:y1, a:b]
            dens.append(float((box < 160).mean()) if box.size else None)
        ref = [d for mi, d in enumerate(dens, 1) if per.get(mi) and d is not None]
        base = sum(ref) / len(ref) if ref else None
        for mi in range(1, total + 1):
            if per.get(mi) or dens[mi - 1] is None or base is None:
                continue
            rows.append((name, si + 1, mi, total, dens[mi - 1], base))

print(f"잉크를 잴 수 있었던 빈 마디 {len(rows)}개\n")
print(f"{'악보':16} {'단':>3} {'마디':>6} {'빈칸잉크':>8} {'이웃평균':>8} {'비율':>6}")
for name, si, mi, tot, d, base in rows:
    r = d / base if base else 0
    print(f"{name:16} {si:3} {mi:3}/{tot:<3} {d:8.3f} {base:8.3f} {r:6.0%}")
if rows:
    rr = sorted(d / b for *_x, d, b in rows)
    print(f"\n이웃 대비 잉크 비율 — 중앙값 {rr[len(rr)//2]:.0%} · "
          f"최소 {rr[0]:.0%} · 최대 {rr[-1]:.0%}")
    print(f"  20% 미만(= 거의 빈 종이) {sum(1 for x in rr if x < .2)}개")
    print(f"  50% 이상(= 뭔가 있다)   {sum(1 for x in rr if x >= .5)}개")
