"""
**두 판독기 교차 검증** — 우리(struct) × homr(MusicXML), 단·마디 단위.

마디마다:
  같게 읽음            → 확정
  한쪽만 박자가 맞음    → 그쪽 채택
  둘 다 맞는데 다름     → 불확실(과금 안 함)
  둘 다 안 맞음         → 깨짐
쪼개진 마디 짝(앞 단 끝 + 다음 단 첫 = 한 마디)과 곡 첫 마디(못갖춘마디)는
박자 검사에서 뺀다. 우리 게이트의 박자 외 사유(2성부·임시표 등)는 그대로 막는다.
"""
import sys, json, os, glob, collections
import xml.etree.ElementTree as ET
MUT = os.environ["MUT"]; HOMR = sys.argv[1]
V = {"whole": 4, "half": 2, "quarter": 1, "eighth": .5, "16th": .25}
BEAT_KINDS = ("음가 합", "개수 판독", "짐작", "빔 묶음")


def homr_systems(path):
    root = ET.parse(path).getroot(); part = next(root.iter("part"))
    div, beats, systems = 1, 4.0, [[]]
    for i, m in enumerate(part.iter("measure")):
        pr = m.find("print")
        if i and pr is not None and pr.get("new-system") == "yes":
            systems.append([])
        at = m.find("attributes")
        if at is not None:
            if at.find("divisions") is not None: div = int(at.find("divisions").text)
            t = at.find("time")
            if t is not None: beats = int(t.find("beats").text) * 4 / int(t.find("beat-type").text)
        seq = []
        for n in m.iter("note"):
            if n.find("chord") is not None or n.find("grace") is not None: continue
            v = n.find("voice")
            if v is not None and v.text != "1": continue
            d = n.find("duration")
            if d is None: continue
            seq.append(("r" if n.find("rest") is not None else "") + f"{int(d.text) / div:g}")
        systems[-1].append(seq)
    return systems, beats


def ours_systems(st):
    out = []
    for s in st.get("systems") or []:
        ms = sorted({n["measure"] for n in s["notes"]})
        out.append([[("r" if n["rest"] else "") + f"{V[n['duration']] * (1.5 if n['dotted'] else 1):g}"
                     for n in s["notes"] if n["measure"] == mi and not n.get("chord")] for mi in ms])
    return out


def total(seq):
    return sum(float(x.lstrip("r")) for x in seq)


def judge(page):
    rec = {r["page"]: r for r in json.load(open(f"{MUT}/eval/sweep_k.json"))}[page]
    other = [k for k in rec["kinds"] if not any(t in k for t in BEAT_KINDS)]
    st = json.load(open(f"{MUT}/eval/sweep_k_structs/{page}.json"))["struct"]
    ours = ours_systems(st)
    full = float(st.get("beats") or 4)
    hp = f"{HOMR}/{page}.musicxml"
    if not os.path.exists(hp):
        return {"page": page, "verdict": "homr없음"}
    hs, _hb = homr_systems(hp)
    c = collections.Counter(); chosen = []
    if len(hs) != len(ours):
        c["단수다름"] += 1
    for si in range(min(len(hs), len(ours))):
        a, b = ours[si], hs[si]
        if len(a) != len(b):
            c["마디수다름"] += 1
            chosen.append([(x, "ours") for x in a]); continue
        chosen.append([])
        for x, y in zip(a, b):
            ox, oy = abs(total(x) - full) < 1e-6, abs(total(y) - full) < 1e-6
            if x == y: chosen[-1].append((x, "agree"))
            elif ox and not oy: chosen[-1].append((x, "ours"))
            elif oy and not ox: chosen[-1].append((y, "homr"))
            elif ox and oy: chosen[-1].append((x, "conflict"))
            else: chosen[-1].append((x, "broken"))
    # 박자 판정 — 곡 첫 마디와 쪼개진 짝은 면제
    bad = []
    for si, ms in enumerate(chosen):
        for mi, (seq, how) in enumerate(ms):
            t = total(seq)
            if how == "conflict": bad.append((si, mi, "conflict")); continue
            if abs(t - full) < 1e-6: continue
            if si == 0 and mi == 0 and t < full: continue
            if mi == len(ms) - 1 and si + 1 < len(chosen) and chosen[si + 1] \
                    and abs(t + total(chosen[si + 1][0][0]) - full) < 1e-6: continue
            if mi == 0 and si > 0 and chosen[si - 1] \
                    and abs(t + total(chosen[si - 1][-1][0]) - full) < 1e-6: continue
            bad.append((si, mi, how))
    how = collections.Counter(h for ms in chosen for _, h in ms)
    ok = not bad and not other and not c
    return {"page": page, "verdict": "통과" if ok else "막힘", "bad": bad[:6], "other": other,
            "align": dict(c), "how": dict(how), "ours_ready": rec["status"] == "ready"}


rows = [judge(os.path.basename(f)[:-5]) for f in sorted(glob.glob(f"{MUT}/eval/sweep_k_structs/*.json"))]
json.dump(rows, open(f"{HOMR}/../ensemble.json", "w"), ensure_ascii=False, indent=1)
v = collections.Counter(r["verdict"] for r in rows)
print(v)
print("우리만 통과", sum(r.get("ours_ready") for r in rows),
      "· 교차 통과", sum(r["verdict"] == "통과" for r in rows),
      "· 그중 새로 통과", sum(r["verdict"] == "통과" and not r.get("ours_ready") for r in rows),
      "· 우리 통과인데 교차에서 막힘", sum(r["verdict"] != "통과" and r.get("ours_ready") for r in rows))
h = collections.Counter()
for r in rows: h.update(r.get("how", {}))
print("마디 판정 합계", dict(h))
al = collections.Counter()
for r in rows: al.update(r.get("align", {}))
print("정렬 실패", dict(al))
