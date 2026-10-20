"""
가사 띠가 남의 단까지 삼키지 않는가.

왜: 이 띠의 픽셀은 **결과 악보에 그대로 붙는다.** 두 단 사이가 넓으면
(단을 하나 놓쳤거나 마지막 단이면) 띠가 한없이 커져 다음 단의 오선·음표가
딸려 온다 — 실측 787개 중 20%가 오선 간격 6배를 넘었고 최악은 35배였다
(중앙값 3.6배). 반대로 너무 조이면 **1·2절 두 줄 가사**가 잘린다.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from PIL import Image
import sheetcv as cv

SP, W = 10, 300


class St:
    def __init__(s, top):
        s.top, s.bottom = top, top + 4 * SP
        s.left, s.right = 0, W - 1
        s.lines = [top + i * SP for i in range(5)]


def page(h, staff_top, lyric_rows, far_content=None):
    """오선 한 단 + 가사 줄들 + (옵션) 아주 아래쪽의 남의 내용."""
    a = np.full((h, W), 255, dtype="uint8")
    for i in range(5):
        a[staff_top + i * SP, 20:W - 20] = 0
    for y in lyric_rows:                       # 가사 한 줄 (오선에 안 붙는다)
        for x in range(30, W - 30, 20):
            # 실측 한 줄 높이는 1.4~3.0칸이다. 얇게 그리면 "글자 줄"로 안 쳐준다.
            a[y:y + 14, x:x + 8] = 0
    if far_content:                            # 다음 단의 오선 — 삼키면 안 된다
        for i in range(5):
            a[far_content + i * SP, 20:W - 20] = 0
    return np.asarray(Image.fromarray(a).convert("L")) < 128


st = St(40)

# ── 한 줄 가사: 띠가 좁아야 한다
ink = page(400, 40, [95])
b = cv.find_lyric_band(ink, st, SP, None)
assert b and (b[1] - b[0]) / SP <= 4.5, f"한 줄인데 띠가 {b} 로 넓다"

# ── 두 줄 가사(1·2절): **둘 다 들어와야** 한다
# 실측 1·2절 줄 사이는 0.6~0.7칸이다 — 그보다 벌어지면 다른 것이다
# **다음 단을 준다.** next_top 이 없으면 창이 오선 아래 5칸뿐이라 두 줄이
# 안 들어간다 — 실제 악보에서는 다음 단까지의 0.75 만큼 본다.
ink2 = page(400, 40, [95, 116])
b2 = cv.find_lyric_band(ink2, st, SP, next_top=260)
assert b2 and b2[1] >= 128, f"둘째 줄이 잘렸다: {b2}"

# ── 다음 단이 멀리 있어도 **삼키지 않는다** (여기가 실제 버그였다)
ink3 = page(900, 40, [95], far_content=400)
b3 = cv.find_lyric_band(ink3, st, SP, next_top=400)
assert b3 and b3[1] < 400, f"다음 단을 삼켰다: {b3}"
assert (b3[1] - b3[0]) / SP <= cv.MAX_LYRIC_BAND + 0.5, \
    f"띠가 상한({cv.MAX_LYRIC_BAND}배)을 넘었다: {(b3[1]-b3[0])/SP:.1f}배"

print("ok")
