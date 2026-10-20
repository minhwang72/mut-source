"""**자동으로 맞는 비율**을 실제 경로로 잰다.

수정 패널에 뜨는 마디 = 사용자가 손봐야 하는 마디다. 그 수가 곧 이 제품이
"자동으로 되는가"의 답이다. 개수 판독(LLM)까지 실제 경로 그대로 쓴다 —
자체 개수로 재면 실제보다 나쁘게 나온다(실측: camp0814b-01 불일치 13 vs 7).
"""
import sys, os, json, warnings
sys.path.insert(0, "tools")
warnings.filterwarnings("ignore")
import numpy as np
from PIL import Image
import probe as P, sheetcv as cv, evaldet as E, detstruct as DS, checkbeats as CB
import readcounts as RC
from ultralytics import YOLO

CACHE = "eval/counts"
os.makedirs(CACHE, exist_ok=True)
M = YOLO("models/omr.pt")
TIE = "models/omr_tie.pt"


def counts_for(path, name):
    """LLM 개수는 비싸므로 한 번 읽고 캐시한다."""
    f = f"{CACHE}/{name}.json"
    if os.path.exists(f):
        return json.load(open(f))["systems"]
    d = RC.read_page(Image.open(path))
    json.dump(d, open(f, "w"), ensure_ascii=False)
    return d["systems"]


def rate(path, name, repair=False):
    counts = counts_for(path, name)
    big, _ = P.upscale(Image.open(path).convert("RGB"))
    ink, st = cv.find_staves_best(big.convert("L"))
    sp = cv.median_spacing(st)
    ex, exr = DS.expects(counts)
    boxes, meta = E.detect_guided(M, big, ex, expect_rests=exr)
    curves = DS.detect_curves(big, TIE, ex, exr) if os.path.exists(TIE) else None
    strict = cv.remove_staff_lines(ink, st, protect_noteheads=True)
    gray = np.asarray(big.convert("L")).astype("float32")
    d = DS.build_from(boxes, st, strict, sp, gray, counts, curves=curves,
                      meta=meta, repair=repair)
    beats = float(d.get("beats") or 4)
    ck = CB.check(d, int(beats))
    over = ck.get("over") or []
    under = ck.get("under") or []
    bad = len(over) + len(under)
    # **얼마나 틀렸나.** 0.5박 차이는 음가 한 단계 — 자동 보정 여지가 있다.
    # 한 마디를 통째로 잃은 것은 검출 문제다. 둘을 섞어 세면 방향을 못 정한다.
    devs = [round(v - beats, 3) for *_h, v in over] + \
           [round(v - beats, 3) for *_h, v in under]
    # 찍어서 채운 마디 — 합은 맞지만 확인이 필요하다
    gm = set()
    for si, sy in enumerate(d["systems"]):
        for n in sy.get("notes", []):
            if n.get("guessed"):
                gm.add((si, n["measure"]))
    return {"ok": ck.get("ok"), "bad": bad, "total": ck.get("ok") + bad,
            "ts": d.get("timeSignature"), "systems": len(d["systems"]),
            "beats": beats, "devs": devs, "guessed": len(gm)}


REPAIR = "--repair" in sys.argv
PAGES = [a for a in sys.argv[1:] if not a.startswith("--")]
print("역산:", "켬" if REPAIR else "끔")
rows = []
print(f"{'악보':16} {'단':>3} {'마디':>4} {'확실':>4} {'찍음':>4} {'깨짐':>4} {'확실률':>6}")
for p in PAGES:
    name = os.path.basename(p).rsplit(".", 1)[0]
    try:
        r = rate(p, name, REPAIR)
        r["page"] = name
        rows.append(r)
        pct = (r["ok"] - r["guessed"]) / max(1, r["total"])
        print(f"{name:16} {r['systems']:3} {r['total']:4} "
              f"{r['ok'] - r['guessed']:4} {r['guessed']:4} {r['bad']:4} {pct:6.0%}")
    except Exception as e:
        print(f"{name:16} 오류 {type(e).__name__}: {e}"[:90])
json.dump(rows, open("eval/auto_rate.json", "w"), ensure_ascii=False, indent=1)
if rows:
    O = sum(r["ok"] for r in rows); T = sum(r["total"] for r in rows)
    B = sum(r["bad"] for r in rows); G = sum(r["guessed"] for r in rows)
    print(f"\n합계 {len(rows)}장 · 마디 {T}")
    print(f"  확실히 맞음 {O-G} ({(O-G)/T:.0%}) · 찍어서 채움 {G} ({G/T:.0%}) "
          f"· 깨진 채 {B} ({B/T:.0%})")
    print(f"  장당 — 확인할 마디 {G/len(rows):.1f} · 고쳐야 할 마디 {B/len(rows):.1f}")
    print(f"  손 안 대도 되는 장 {sum(1 for r in rows if r['bad']==0 and r['guessed']==0)}/{len(rows)}")
    print(f"  깨진 마디 없는 장 {sum(1 for r in rows if r['bad']==0)}/{len(rows)}")

    import collections
    all_d = [d for r in rows for d in r["devs"]]
    print(f"\n=== 편차 분포 ({len(all_d)}개) ===")
    buck = collections.Counter()
    for d in all_d:
        a = abs(d)
        if a <= 0.5: buck["≤0.5박 (음가 한 단계)"] += 1
        elif a <= 1.0: buck["0.5~1.0박"] += 1
        elif a <= 2.0: buck["1~2박"] += 1
        else: buck["2박 초과 (마디를 통째로)"] += 1
    for k in ["≤0.5박 (음가 한 단계)", "0.5~1.0박", "1~2박", "2박 초과 (마디를 통째로)"]:
        v = buck.get(k, 0)
        print(f"  {k:24} {v:4}  {v/max(1,len(all_d)):5.0%}")
    print("\n가장 흔한 편차값:")
    for d, c in collections.Counter(all_d).most_common(8):
        print(f"  {d:+6}박  {c:3}개")
