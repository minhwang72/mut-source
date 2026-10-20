"""
통과 직전 장(깨진 마디 0~1개)의 **문제 마디만** 원본과 나란히 잘라 본다.
배포 경로·캐시 그대로. 결과 PNG 는 상업 악보 크롭이라 저장소에 두지 않는다.
사용: python eval/near_sheets.py <출력폴더> 장1 장2 …
"""
import sys
sys.path.insert(0, "tools"); sys.path.insert(0, "server")
import devcache; devcache.install()
import serve
from PIL import Image, ImageDraw
serve.STATE["mode"] = "ai"
OUT = sys.argv[1]
D = {"whole": "1", "half": "2", "quarter": "4", "eighth": "8", "16th": "16"}
V = {"whole": 4, "half": 2, "quarter": 1, "eighth": .5, "16th": .25}
U = {"whole": 32, "half": 16, "quarter": 8, "eighth": 4, "16th": 2}
for p in sys.argv[2:]:
    ex = serve.read_sheet(open(f"악보샘플/이미지/{p}.png", "rb").read(), None)
    st, geo = ex["struct"], ex["geometry"]
    sc, beats = geo["scale"], float(st.get("beats") or 4)
    im = Image.open(f"악보샘플/이미지/{p}.png").convert("RGB")
    tiles = []
    for s in st["systems"]:
        g = geo["systems"][s["system"]]
        edges = [g["left"]] + list(g.get("bars") or []) + [g["right"]]
        per, why, pos, ends = {}, {}, {}, {}
        for n in s["notes"]:
            if n.get("chord"):
                continue
            mi = n["measure"]
            per[mi] = per.get(mi, 0) + V[n["duration"]] * (1.5 if n["dotted"] else 1)
            pos[mi] = pos.get(mi, 0) + U[n["duration"]] * (3 if n["dotted"] else 2) // 2
            if n.get("beamGroup", -1) >= 0 and not n["rest"]:
                ends[(mi, n["beamGroup"])] = pos[mi]
            if n.get("guessed"):
                why.setdefault(mi, set()).add("GUESS")
        for mi, v in per.items():
            if abs(v - beats) > 1e-6:
                why.setdefault(mi, set()).add(f"SUM{v:g}")
        for (mi, _g), e in ends.items():
            if e % 4:
                why.setdefault(mi, set()).add("BEAM")
        for mi in sorted(why):
            if mi >= len(edges):
                continue
            x0, x1 = edges[mi - 1], edges[mi]
            y0, y1 = g["staffTop"] - 4 * g["spacing"], g["staffBottom"] + 3 * g["spacing"]
            c = im.crop((int(x0 / sc) - 6, int(y0 / sc), int(x1 / sc) + 6, int(y1 / sc)))
            c = c.resize((c.width * 2, c.height * 2))
            txt = " ".join(("r" if n["rest"] else "") + D[n["duration"]] + ("." if n["dotted"] else "")
                           + ("?" if n.get("guessed") else "") + ("*" if n.get("fitted") else "")
                           for n in s["notes"] if n["measure"] == mi and not n.get("chord"))
            lab = f"{p} S{s['system']} M{mi} {','.join(sorted(why[mi]))}: {txt}"
            t = Image.new("RGB", (max(c.width, 700), c.height + 16), "white")
            ImageDraw.Draw(t).text((3, 2), lab, fill="black"); t.paste(c, (0, 16)); tiles.append(t)
    if tiles:
        W = max(t.width for t in tiles); H = sum(t.height + 4 for t in tiles)
        sheet = Image.new("RGB", (W, H), "#bbb"); y = 0
        for t in tiles:
            sheet.paste(t, (0, y)); y += t.height + 4
        sheet.save(f"{OUT}/near_{p}.png")
        print(p, len(tiles), flush=True)
