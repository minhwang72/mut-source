import sys, os, warnings; sys.path.insert(0,"tools"); warnings.filterwarnings("ignore")
import numpy as np
from PIL import Image, ImageDraw
sys.path.insert(0,"eval")
from stems import stems_of
import probe as P, sheetcv as cv
page, si = sys.argv[1], int(sys.argv[2])
big,_=P.upscale(Image.open(page).convert("RGB"))
ink,st=cv.find_staves_best(big.convert("L")); sp=cv.median_spacing(st)
strict=cv.remove_staff_lines(ink,st,protect_noteheads=True)
import layout as L, evaldet as E
from ultralytics import YOLO
boxes,_=E.detect_by_staff(YOLO("models/omr.pt"),big,0.50)
s=st[si]
mid=(s.top+s.bottom)/2; half=(s.bottom-s.top)*1.4
near=[b for b in boxes if abs(b["y"]+b["h"]/2-mid)<half]
firsts=[b["x"] for b in near if b["class"].startswith(("notehead","rest"))]
x_from=(min(firsts)-sp*0.6) if firsts else None
heads=[b for b in near if b["class"].startswith("notehead")]
try: bars=L.barlines_of(strict,s,sp,heads,x_from)
except Exception: bars=[]
xs=stems_of(strict,s,sp,x_from,bars)
print("x_from",x_from,"bars",[round(b) for b in bars])
im=big.convert("RGB")
d=ImageDraw.Draw(im)
for x in xs:
    d.line([(x,s.top-sp*3),(x,s.bottom+sp*3)],fill=(255,0,0),width=2)
c=im.crop((0,max(0,int(s.top-sp*5)),im.width,min(im.height,int(s.bottom+sp*5))))
k=1500/c.width; c=c.resize((1500,int(c.height*k)),Image.LANCZOS)
c.save("eval/stems_draw.png")
print(f"기둥 {len(xs)}개 · 간격 {sp:.0f}px → eval/stems_draw.png")
