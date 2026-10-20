"""우리 struct 와 homr MusicXML 의 음가 순서를 마디 단위로 대조한다."""
import sys, json, os
import xml.etree.ElementTree as ET
p = sys.argv[1]
V = {"whole": 4, "half": 2, "quarter": 1, "eighth": .5, "16th": .25}
st = json.load(open(f"{os.environ['MUT']}/eval/sweep_k_structs/{p}.json"))["struct"]
ours = []
for s in st["systems"]:
    for mi in sorted({n["measure"] for n in s["notes"]}):
        ours.append([("r" if n["rest"] else "") + f"{V[n['duration']] * (1.5 if n['dotted'] else 1):g}"
                     for n in s["notes"] if n["measure"] == mi and not n.get("chord")])
root = ET.parse(sys.argv[2]).getroot()
part = next(root.iter("part")); div = 1; theirs = []
for m in part.iter("measure"):
    at = m.find("attributes")
    if at is not None and at.find("divisions") is not None: div = int(at.find("divisions").text)
    seq = []
    for n in m.iter("note"):
        if n.find("chord") is not None or n.find("grace") is not None: continue
        d = n.find("duration")
        if d is None: continue
        seq.append(("r" if n.find("rest") is not None else "") + f"{int(d.text) / div:g}")
    theirs.append(seq)
same = sum(a == b for a, b in zip(ours, theirs))
print(f"{p}: 마디 우리 {len(ours)} · homr {len(theirs)} · 음가 순서 완전 일치 {same}")
for i, (a, b) in enumerate(zip(ours, theirs)):
    if a != b: print(f"  마디{i+1:3} 우리 {' '.join(a):40} | homr {' '.join(b)}")
