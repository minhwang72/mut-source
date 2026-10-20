"""
**회색지대 하한을 내리면 깨진 마디가 얼마나 줄어드나.**

변수는 하나다 — MUTE_DOT_PROMOTE. 이전에 한 번, 다섯 가지를 한꺼번에
바꾼 학습을 돌렸다가 해석이 불가능했다. 같은 실수를 반복하지 않는다.

각 장을 두 번 읽고 **마디 단위로** 비교한다.
  나아짐 — 깨졌던 마디가 맞아졌다
  나빠짐 — 맞던 마디가 깨졌다 (이게 0 이 아니면 켜면 안 된다)
"""
import os, sys, json, collections, warnings
sys.path.insert(0, "tools"); sys.path.insert(0, "server")
warnings.filterwarnings("ignore")

DUR = {"whole": 32, "half": 16, "quarter": 8, "eighth": 4, "16th": 2}


def broken(st):
    """{(단, 마디): 합} 중 기준과 다른 것."""
    full = int(round(float(st.get("beats") or 4) * 8))
    out = {}
    for si, s in enumerate(st.get("systems") or []):
        per = collections.defaultdict(int)
        for n in s.get("notes") or []:
            if n.get("chord"):
                continue
            v = DUR.get(n.get("duration"), 0)
            per[n.get("measure")] += v * 3 // 2 if n.get("dotted") else v
        for mi, got in per.items():
            if got != full:
                out[(si, mi)] = got
    return out


VAR = os.environ.get("AB_VAR", "MUTE_DOT_GRAY")
BASE = os.environ.get("AB_BASE", "0.40")
TEST = os.environ.get("AB_TEST", "0.30")


def read(path, on):
    os.environ["MUTE_DOT_PROMOTE"] = "1"
    os.environ[VAR] = TEST if on else BASE
    for m in ("local_reader", "detstruct", "fitdur", "durations"):
        sys.modules.pop(m, None)
    import local_reader as LR
    return LR.read_sheet_local(open(path, "rb").read())


PAGES = sorted(sys.argv[1:] or
               [f"악보샘플/이미지/{f}" for f in os.listdir("악보샘플/이미지")
                if f.endswith(".png")])
tot_off, tot_on, better, worse, promoted = 0, 0, 0, 0, 0
rows = []
for p in PAGES:
    name = os.path.basename(p).rsplit(".", 1)[0]
    try:
        a, b = broken(read(p, False)["struct"]), None
        exb = read(p, True)
        b = broken(exb["struct"])
        pr = sum(1 for s in exb["struct"]["systems"]
                 for n in (s.get("notes") or []) if n.get("dotPromoted"))
    except Exception as e:                       # noqa: BLE001
        print(f"{name:18} 오류 {type(e).__name__}: {str(e)[:60]}", flush=True)
        continue
    w = len(set(b) - set(a))
    g = len(set(a) - set(b))
    tot_off += len(a); tot_on += len(b); better += g; worse += w; promoted += pr
    rows.append({"page": name, "off": len(a), "on": len(b),
                 "better": g, "worse": w, "promoted": pr})
    flag = "  ← 나빠짐" if w else ""
    print(f"{name:18} {BASE} {len(a):3} → {TEST} {len(b):3}  "
          f"(나아짐 {g:2} · 나빠짐 {w:2} · 승격 {pr:2}){flag}", flush=True)

print(f"\n== {len(rows)}장")
print(f"  깨진 마디  {BASE} {tot_off} → {TEST} {tot_on}  (-{tot_off - tot_on})")
print(f"  나아짐 {better} · **나빠짐 {worse}** · 승격한 붙임점 {promoted}")
json.dump(rows, open("eval/dots_ab.json", "w"), ensure_ascii=False, indent=1)
