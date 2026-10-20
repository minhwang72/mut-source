"""
**반복 비교가 고친 마디를 눈으로 본다.**

반복 비교는 "같은 그림을 두 번 다르게 읽었다"를 근거로 한쪽을 고친다.
그런데 **짝을 잘못 지었으면** 다른 두 마디를 같다고 우기며 멀쩡한 쪽을
망친다. 박자 지표로는 안 보인다 — 고친 쪽 합이 맞아지니까.

그래서 고친 마디와 그 짝을 **나란히** 잘라 붙인다. 두 그림이 같아 보이면
짝짓기가 맞은 것이고, 달라 보이면 잘못 고친 것이다.
"""
import os, sys, warnings, collections
sys.path.insert(0, "tools"); sys.path.insert(0, "server")
warnings.filterwarnings("ignore")
os.environ["MUTE_DOT_PROMOTE"] = "1"
os.environ["MUTE_REPEAT_FIX"] = "1"
import numpy as np
import local_reader as LR
import sheetcv as cv
import repeats as R
from PIL import Image, ImageDraw

PAGES = sys.argv[1:] or sorted(
    f"악보샘플/이미지/{f}" for f in os.listdir("악보샘플/이미지")
    if f.endswith(".png"))

rows = []
for p in PAGES:
    try:
        ex = LR.read_sheet_local(open(p, "rb").read())
    except Exception:                            # noqa: BLE001
        continue
    st = ex["struct"]
    hit = [(si, n.get("measure")) for si, s in enumerate(st.get("systems") or [])
           for n in (s.get("notes") or []) if n.get("repeatFixed")]
    if not hit:
        continue
    # 어느 단끼리 짝지었는지 다시 구한다 — 그림을 나란히 놓으려면 필요하다
    img = Image.open(p).convert("RGB")
    big, staves = None, None
    try:
        ink, staves = cv.find_staves_best(img)
        strict = cv.remove_staff_lines(ink, staves, protect_noteheads=True)
        sp = cv.median_spacing(staves)
        pairs = R.find_pairs(strict, staves, sp)
    except Exception as e:                       # noqa: BLE001
        print(f"  {os.path.basename(p)} 짝 계산 실패: {type(e).__name__}")
        continue
    seen = set()
    for si, mi in hit:
        if (si, mi) in seen:
            continue
        seen.add((si, mi))
        mate = next((j if i == si else i for i, j, _s in pairs
                     if si in (i, j)), None)
        if mate is None:
            continue
        rows.append((os.path.basename(p)[:-4], si, mate, mi, img, staves))

print(f"반복 비교가 고친 마디 {len(rows)}개")
if not rows:
    raise SystemExit

def band(img, staves, si, scale=1.0):
    """한 단을 가사·기둥까지 넉넉히 포함해 잘라 온다."""
    s = staves[si]
    top, bot = s.top / scale, s.bottom / scale
    pad = (bot - top) * 1.3 + 10
    return img.crop((0, int(max(0, top - pad)),
                     img.width, int(min(img.height, bot + pad))))

tiles = []
for name, si, mate, mi, img, staves in rows[:8]:
    a, b = band(img, staves, si), band(img, staves, mate)
    w = max(a.width, b.width)
    t = Image.new("RGB", (w, a.height + b.height + 26), "white")
    t.paste(a, (0, 0)); t.paste(b, (0, a.height + 26))
    d = ImageDraw.Draw(t)
    d.text((4, a.height + 6), f"{name}  단{si+1} ↔ 단{mate+1}  마디{mi+1}", fill=(180, 30, 20))
    tiles.append(t)

W = max(t.width for t in tiles)
H = sum(t.height + 14 for t in tiles)
sheet = Image.new("RGB", (W, H), "white")
y = 0
for t in tiles:
    sheet.paste(t, (0, y)); y += t.height + 14
if sheet.width > 1500:
    sheet = sheet.resize((1500, int(sheet.height * 1500 / sheet.width)), Image.LANCZOS)
sheet.save("/tmp/repeat_eyes.png")
print("저장 /tmp/repeat_eyes.png", sheet.size)
