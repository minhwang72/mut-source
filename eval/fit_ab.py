"""
**fit_page 는 깨진 마디 수로 판단할 수 없다.**

이 수리기는 합이 맞을 때까지 음가를 비튼다. 그러니 "깨진 마디가 줄었다"는
결과가 아니라 **정의**다. 그 숫자로 채택을 정하면 순환논법이다.

대신 세 축을 함께 본다.
  ① 깨진 마디      — 줄어드는 게 당연. 참고용
  ② 비튼/찍은 음표  — **비용**. 원본과 다를 수 있는 음표의 수
  ③ 게이트 통과 장  — **사업적 결과**. 통과하면 돈을 받는다. 찍은 악보에
                     돈을 받는 일이 여기서 생긴다
"""
import os, sys, warnings, collections, json
sys.path.insert(0, "tools"); sys.path.insert(0, "server")
warnings.filterwarnings("ignore")
os.environ["MUTE_DOT_PROMOTE"] = "1"
os.environ["MUTE_REPEAT_FIX"] = "1"
os.environ["MUTE_SPLIT_MERGED"] = "1"

DUR = {"whole": 32, "half": 16, "quarter": 8, "eighth": 4, "16th": 2}


def read(path, on):
    os.environ["MUTE_FIT_PAGE"] = "1" if on else "0"
    for m in ("local_reader", "detstruct", "fitdur", "durations", "repeats"):
        sys.modules.pop(m, None)
    import local_reader as LR
    return LR.read_sheet_local(open(path, "rb").read())


def stat(ex):
    st = ex["struct"]
    full = int(round(float(st.get("beats") or 4) * 8))
    bad = notes = guessed = fitted = 0
    for s in st.get("systems") or []:
        per = collections.defaultdict(int)
        for n in s.get("notes") or []:
            notes += 1
            guessed += bool(n.get("guessed"))
            fitted += bool(n.get("fitted"))
            if n.get("chord"):
                continue
            v = DUR.get(n.get("duration"), 0)
            per[n.get("measure")] += v * 3 // 2 if n.get("dotted") else v
        bad += sum(1 for v in per.values() if v != full)
    g = ex["qualityGate"]
    return bad, notes, guessed, fitted, g["status"], len(g.get("blocking") or [])


PAGES = sorted(f"악보샘플/이미지/{f}" for f in os.listdir("악보샘플/이미지")
               if f.endswith(".png"))
tot = collections.Counter()
flip = []
for p in PAGES:
    name = os.path.basename(p)[:-4]
    try:
        a, b = stat(read(p, False)), stat(read(p, True))
    except Exception as e:                       # noqa: BLE001
        continue
    tot["bad_off"] += a[0]; tot["bad_on"] += b[0]
    tot["notes"] += b[1]
    tot["guessed"] += b[2]; tot["fitted"] += b[3]
    tot["guessed_off"] += a[2]; tot["fitted_off"] += a[3]
    tot["pages"] += 1
    tot["ready_off"] += a[4] == "ready"
    tot["ready_on"] += b[4] == "ready"
    if a[4] != b[4]:
        flip.append((name, a[4], b[4], b[2], b[3]))
    print(f"{name:18} 깨짐 {a[0]:3}→{b[0]:3}  찍음 {a[2]:3}→{b[2]:3}  "
          f"비틂 {a[3]:3}→{b[3]:3}  게이트 {a[5]:3}→{b[5]:3}", flush=True)

n = max(1, tot["pages"])
print(f"\n== {tot['pages']}장 · 음표 {tot['notes']}")
print(f"  ① 깨진 마디      {tot['bad_off']} → {tot['bad_on']}  "
      f"({tot['bad_on'] - tot['bad_off']:+d})   ※ 줄어드는 게 정의다")
print(f"  ② 찍은 음표      {tot['guessed_off']} → {tot['guessed']}   "
      f"(전체의 {tot['guessed']/max(1,tot['notes']):.1%})")
print(f"     비튼 음표      {tot['fitted_off']} → {tot['fitted']}   "
      f"(전체의 {tot['fitted']/max(1,tot['notes']):.1%})")
print(f"  ③ 게이트 통과 장  {tot['ready_off']} → {tot['ready_on']} / {tot['pages']}")
print(f"\n게이트 판정이 바뀐 장 {len(flip)}")
for name, x, y, g, fi in flip[:12]:
    print(f"  {name:18} {x} → {y}  (그 장의 찍은 음표 {g} · 비튼 음표 {fi})")
json.dump({"tot": dict(tot), "flip": flip}, open("eval/fit_ab.json", "w"),
          ensure_ascii=False, indent=1)
