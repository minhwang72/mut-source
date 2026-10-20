"""
**승격한 붙임점이 진짜 거기 있나 — 눈으로 본다.**

박자 지표는 "합이 맞는가"만 본다. 엉뚱한 음표에 점을 붙여도 합은 맞으므로
지표는 통과시킨다(예전에 unchord_broken 이 정확히 그렇게 지표만 좋아지고
음악이 깨졌다). 그래서 문턱을 내리기 전에 화소를 본다.

문턱을 내려야만 승격된 음표(0.30 <= dotScore < 0.40)의 머리 오른쪽을
잘라 한 장으로 붙인다. 점이 보이면 맞는 것이고, 안 보이면 지어낸 것이다.
"""
import os, sys, warnings
sys.path.insert(0, "tools"); sys.path.insert(0, "server")
warnings.filterwarnings("ignore")
os.environ["MUTE_DOT_PROMOTE"] = "1"
os.environ["MUTE_DOT_GRAY"] = os.environ.get("EYES_GRAY", "0.30")
import local_reader as LR
from PIL import Image, ImageDraw

LO, HI = 0.30, 0.40
PAGES = sys.argv[1:] or ["악보샘플/이미지/wish0920-6.png",
                         "악보샘플/이미지/now0918-7.png",
                         "악보샘플/이미지/day2sb-4.png"]
crops = []
for p in PAGES:
    try:
        ex = LR.read_sheet_local(open(p, "rb").read())
    except Exception as e:                       # 빈 표지 등은 건너뛴다
        print(f"  건너뜀 {os.path.basename(p)}: {str(e)[:40]}")
        continue
    img = Image.open(p).convert("RGB")
    scale = float((ex.get("geometry") or {}).get("scale") or 1.0)
    for s in (ex["struct"].get("systems") or []):
        for n in (s.get("notes") or []):
            sc = float(n.get("dotScore") or 0)
            if not (n.get("dotPromoted") and LO <= sc < HI and "head" in n):
                continue
            h = n["head"]
            # 좌표는 확대본 기준이라 원본으로 되돌린다
            x, y, w, hh = (h["x"] / scale, h["y"] / scale,
                           h["w"] / scale, h["h"] / scale)
            pad = w * 1.6
            box = (int(x - pad * .4), int(y - pad * 1.4),
                   int(x + w + pad * 3.4), int(y + hh + pad * 1.4))
            c = img.crop(box).resize(((box[2]-box[0])*4, (box[3]-box[1])*4), Image.LANCZOS)
            d = ImageDraw.Draw(c)
            # 머리 위치를 표시해 어디가 그 음표인지 알 수 있게
            d.rectangle([int((x-box[0])*4), int((y-box[1])*4),
                         int((x+w-box[0])*4), int((y+hh-box[1])*4)],
                        outline=(200, 40, 30), width=2)
            crops.append((sc, c))

crops.sort(key=lambda t: t[0])
print(f"문턱을 내려야만 승격된 붙임점 {len(crops)}개")
if not crops:
    raise SystemExit
cw = max(c.width for _s, c in crops)
ch = max(c.height for _s, c in crops)
cols = 5
rows = (len(crops) + cols - 1) // cols
sheet = Image.new("RGB", (cols * cw, rows * (ch + 16)), "white")
dr = ImageDraw.Draw(sheet)
for i, (sc, c) in enumerate(crops[:cols * rows]):
    x, y = (i % cols) * cw, (i // cols) * (ch + 16)
    sheet.paste(c, (x, y))
    dr.text((x + 3, y + ch + 2), f"{sc:.3f}", fill=(20, 20, 20))
sheet.save("/tmp/dot_eyes.png")
print("저장 /tmp/dot_eyes.png", sheet.size)
