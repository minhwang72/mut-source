"""
**1차 빔과 같은 자리에 겹친 2차 빔(유령)이 얼마나 흔한가.**

day2conti-2 단1: beam1(0.47) 위에 거의 같은 상자의 beam2(0.38)가 있어
점8분이 16분으로 읽혔다. 진짜 겹빔도 상자가 겹칠 수 있으므로, 105장에서
겹친 쌍을 모아 신뢰도·크기와 함께 잘라 눈으로 본다. 배포 경로·캐시 그대로.
"""
import sys, os, json
sys.path.insert(0, "tools"); sys.path.insert(0, "server")
import devcache; devcache.install()
import serve, durations as D
from PIL import Image
serve.STATE["mode"] = "ai"
OUT = sys.argv[1]
pairs = []
orig = D.read_durations
cur = {}


def ov(a, b, k0, k1):
    lo, hi = max(a[k0], b[k0]), min(a[k0] + a[k1], b[k0] + b[k1])
    return max(0.0, hi - lo) / max(1e-6, min(a[k1], b[k1]))


def spy(boxes, spacing, gray=None, mask_extra=None, nostaff=None):
    b1 = [b for b in boxes if b["class"] == "beam1"]
    for b in boxes:
        if b["class"] != "beam2":
            continue
        for a in b1:
            if ov(a, b, "x", "w") > 0.8 and ov(a, b, "y", "h") > 0.6:
                pairs.append({"page": cur["p"], "sp": spacing, "b1": a, "b2": b})
    return orig(boxes, spacing, gray, mask_extra, nostaff)


D.read_durations = spy
import detstruct; detstruct.D.read_durations = spy
for f in sorted(os.listdir("악보샘플/이미지")):
    cur["p"] = f[:-4]
    try:
        serve.read_sheet(open(f"악보샘플/이미지/{f}", "rb").read(), None)
    except Exception:
        pass
seen = set(); uniq = []
for q in pairs:                      # promote_heads 재시도로 같은 상자가 여러 번 온다
    k = (q["page"], round(q["b2"]["x"]), round(q["b2"]["y"]))
    if k not in seen:
        seen.add(k); uniq.append(q)
json.dump(uniq, open(f"{OUT}/ghost_beams.json", "w"))
print("겹친 쌍", len(uniq), "장", len({q["page"] for q in uniq}))
