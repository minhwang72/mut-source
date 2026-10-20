"""색 필터가 **실제로 지우는 것**을 잘라 본다. 라벨이 없으니 눈으로 판정한다.

앞 시도의 실패: 상자 안 '잉크로 볼 만큼 어두운' 화소 전체의 채도를 썼더니,
형광펜 위에 있는 **진짜 음표**까지 유채색으로 잡혔다. 그래서 여기서는
**가장 어두운 화소들**만 본다 — 청록 위 검은 머리는 순검정이 남지만
빨간 글자는 아무리 진해도 순검정이 안 된다.
"""
import sys, os, json, glob, warnings
sys.path.insert(0, "tools")
warnings.filterwarnings("ignore")
import numpy as np
from PIL import Image, ImageDraw
import probe as P, sheetcv as cv, evaldet as E
from ultralytics import YOLO

M = YOLO("models/omr.pt")
TARGET = E.INPUT_SPACING
THRESH = float(sys.argv[1]) if len(sys.argv) > 1 else 0.20
ABS_MIN = float(sys.argv[2]) if len(sys.argv) > 2 else 0.40


def dark_sat(rgb, b):
    """파이프라인과 같은 판정. (절대채도, 버릴지)"""
    x, y = b[0], b[1]
    w, h = b[2] - b[0], b[3] - b[1]
    sa = E._sat_dark(rgb[max(0,int(y)):int(b[3]), max(0,int(x)):int(b[2])].astype("float32"))
    return sa, E.colored(rgb, x, y, w, h)


tiles, n_all, n_cut = [], 0, 0
for f in sorted(glob.glob("eval/counts/*.json")):
    name = os.path.basename(f)[:-5]
    img = f"악보샘플/이미지/{name}.png"
    if not os.path.exists(img):
        continue
    big, _ = P.upscale(Image.open(img).convert("RGB"))
    rgb = np.asarray(big)
    ink, st = cv.find_staves_best(big.convert("L"))
    sp = cv.median_spacing(st)
    for i, s_ in enumerate(st):
        y0 = max(0, int(s_.top - sp * 5)); y1 = min(big.height, int(s_.bottom + sp * 6))
        strip = big.crop((0, y0, big.width, y1))
        need = int(strip.width * (TARGET / sp)); size = 32 * max(1, round(need / 32))
        r = M.predict(strip, imgsz=size, conf=0.05, verbose=False)[0]
        for b, cl, c in zip(r.boxes.xyxy.tolist(), r.boxes.cls.tolist(), r.boxes.conf.tolist()):
            if not r.names[int(cl)].startswith("notehead"):
                continue
            box = (b[0], b[1] + y0, b[2], b[3] + y0)
            n_all += 1
            if E.washed(rgb, y0, y1):
                continue
            sa, cut = dark_sat(rgb, box)
            if not cut:
                continue
            n_cut += 1
            pad = sp * 1.6
            bb = (max(0, int(box[0]-pad)), max(0, int(box[1]-pad)),
                  min(big.width, int(box[2]+pad)), min(big.height, int(box[3]+pad)))
            t = big.crop(bb)
            if t.width < 4 or t.height < 4:
                continue
            k = 90 / max(t.width, t.height)
            tiles.append((t.resize((max(1,int(t.width*k*2)), max(1,int(t.height*k*2))), Image.LANCZOS),
                          f"{name[:9]}·{i+1} a{sa:.2f}"))
    print(name, flush=True)

print(f"\n검출 머리 {n_all}개 중 색 필터로 버릴 것 {n_cut}개 ({n_cut/max(1,n_all):.1%})")
if tiles:
    COLS, CW, CH = 8, 190, 210
    rows_ = (len(tiles)+COLS-1)//COLS
    out = Image.new("RGB", (COLS*CW, rows_*CH), "white"); d = ImageDraw.Draw(out)
    for n,(t,lab) in enumerate(tiles[:96]):
        cx, cy = (n%COLS)*CW, (n//COLS)*CH
        out.paste(t, (cx+(CW-t.width)//2, cy+18)); d.text((cx+4,cy+2), lab, fill=(200,0,0))
    out.save("eval/color_cut.png"); print("→ eval/color_cut.png", out.size)
