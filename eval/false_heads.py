"""**군더더기 후보 2개의 정체를 본다.**

문턱 0.05 에서는 진짜 음표가 다 들어 있고(81% 단), 걸러낼 가짜가 단당 2개다.
그 2개가 무엇인지 알아야 합성 데이터에 무엇을 넣을지 정할 수 있다.

정답 위치는 없고 개수만 있으므로, **점수 상위 N개(N=정답)를 진짜로 보고
나머지를 용의자로** 자른다. detect_guided 가 실제로 쓰는 규칙과 같다.
"""
import sys, os, json, glob, warnings
sys.path.insert(0, "tools")
warnings.filterwarnings("ignore")
from PIL import Image, ImageDraw
import probe as P, sheetcv as cv, evaldet as E
from ultralytics import YOLO

OUT = sys.argv[2] if len(sys.argv) > 2 else "eval/false_heads.png"
M = YOLO(sys.argv[1] if len(sys.argv) > 1 else "models/omr.pt")
print("모델:", sys.argv[1] if len(sys.argv) > 1 else "models/omr.pt")
TARGET = E.INPUT_SPACING
tiles, seen = [], []

for f in sorted(glob.glob("eval/counts/*.json")):
    name = os.path.basename(f)[:-5]
    img = f"악보샘플/이미지/{name}.png"
    if not os.path.exists(img):
        continue
    llm = [s["notes"] for s in json.load(open(f))["systems"]]
    big, _ = P.upscale(Image.open(img).convert("RGB"))
    ink, st = cv.find_staves_best(big.convert("L"))
    sp = cv.median_spacing(st)
    for i, s_ in enumerate(st):
        if i >= len(llm):
            break
        y0 = max(0, int(s_.top - sp * 5)); y1 = min(big.height, int(s_.bottom + sp * 6))
        strip = big.crop((0, y0, big.width, y1))
        need = int(strip.width * (TARGET / sp)); size = 32 * max(1, round(need / 32))
        r = M.predict(strip, imgsz=size, conf=0.05, verbose=False)[0]
        hs = sorted(((b[0], b[1] + y0, b[2], b[3] + y0, float(c))
                     for b, cl, c in zip(r.boxes.xyxy.tolist(), r.boxes.cls.tolist(),
                                         r.boxes.conf.tolist())
                     if r.names[int(cl)].startswith("notehead")),
                    key=lambda t: -t[4])
        kept = []
        for x0, ya, x1, yb, c in hs:
            cx, cy = (x0+x1)/2, (ya+yb)/2
            if any(abs(cx-(k[0]+k[2])/2) < sp*0.5 and abs(cy-(k[1]+k[3])/2) < sp*0.5
                   for k in kept):
                continue
            kept.append((x0, ya, x1, yb, c))
        extra = kept[llm[i]:]          # 정답 개수를 넘는 것 = 용의자
        for x0, ya, x1, yb, c in extra[:3]:
            pad = sp * 1.6
            box = (max(0, int(x0-pad)), max(0, int(ya-pad)),
                   min(big.width, int(x1+pad)), min(big.height, int(yb+pad)))
            t = big.crop(box)
            if t.width < 4 or t.height < 4:
                continue
            k = 90 / max(t.width, t.height)
            t = t.resize((max(1,int(t.width*k*2)), max(1,int(t.height*k*2))), Image.LANCZOS)
            tiles.append((t, f"{name[:10]}·단{i+1} {c:.2f}"))
    print(name, flush=True)

print(f"\n용의자 {len(tiles)}개")
COLS, CW, CH = 8, 190, 210
rows = (len(tiles) + COLS - 1) // COLS
out = Image.new("RGB", (COLS*CW, rows*CH), "white")
d = ImageDraw.Draw(out)
for n, (t, lab) in enumerate(tiles):
    cx, cy = (n % COLS)*CW, (n // COLS)*CH
    out.paste(t, (cx + (CW-t.width)//2, cy + 18))
    d.text((cx+4, cy+2), lab, fill=(200, 0, 0))
out.save(OUT)
print("→", OUT, out.size)
