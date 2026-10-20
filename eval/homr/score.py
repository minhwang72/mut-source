"""세 엔진을 같은 기준으로: 마디 수 · 박자가 맞는 마디 비율 · 음표 수.
MusicXML(oemer·homr)과 우리 struct(json)를 모두 읽는다."""
import sys, json, glob, os
import xml.etree.ElementTree as ET

def musicxml(path):
    root = ET.parse(path).getroot()
    out = []
    for part in root.iter("part"):
        div, beats, btype = 1, 4, 4
        for m in part.iter("measure"):
            at = m.find("attributes")
            if at is not None:
                if at.find("divisions") is not None: div = int(at.find("divisions").text)
                t = at.find("time")
                if t is not None:
                    beats, btype = int(t.find("beats").text), int(t.find("beat-type").text)
            tot, notes = 0, 0
            for n in m.iter("note"):
                if n.find("chord") is not None or n.find("grace") is not None: continue
                v = n.find("voice")
                if v is not None and v.text not in ("1", None): continue
                d = n.find("duration")
                if d is None: continue
                tot += int(d.text); notes += n.find("rest") is None
            out.append((tot / div, beats * 4 / btype, notes))
        break                                   # 첫 파트만
    return out

def ours(path):
    st = json.load(open(path))["struct"]
    V = {"whole": 4, "half": 2, "quarter": 1, "eighth": .5, "16th": .25}
    full = float(st.get("beats") or 4); out = []
    for s in st.get("systems") or []:
        per, cnt = {}, {}
        for n in s["notes"]:
            if n.get("chord"): continue
            per[n["measure"]] = per.get(n["measure"], 0) + V[n["duration"]] * (1.5 if n["dotted"] else 1)
            cnt[n["measure"]] = cnt.get(n["measure"], 0) + (not n["rest"])
        out += [(per[k], full, cnt[k]) for k in sorted(per)]
    return out

def summary(ms):
    if not ms: return "결과 없음"
    ok = sum(1 for t, f, _ in ms if abs(t - f) < 1e-6)
    return f"마디 {len(ms):3} · 박자 맞음 {ok:3} ({ok / len(ms):.0%}) · 음표 {sum(n for *_, n in ms):4}"

for p in sys.argv[1:]:
    print(p)
    print("   우리  ", summary(ours(f"{os.environ['MUT']}/eval/sweep_k_structs/{p}.json")))
    for eng, f in (("oemer", f"out_oemer/{p}.musicxml"), ("homr ", f"homr_in/{p}.musicxml")):
        print("  ", eng, summary(musicxml(f)) if os.path.exists(f) else "아직 없음")
