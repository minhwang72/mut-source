"""조표를 오선 위 자리로 센다 — 검출기로는 못 세기 때문이다.

실측 정답 7장: 검출기 4/7(♯3개를 1개, 4개를 1개, 5개를 1개로), 자리 세기 7/7.
**조성이 틀리면 악보 전체의 음이 틀린다** — 짐작한 음표 몇 개와 차원이 다르다.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import keysigpos as KP


class Staff:
    def __init__(self, top, sp):
        self.lines = [top + i * sp for i in range(5)]
        self.top, self.bottom, self.left = top, top + 4 * sp, 10


def canvas(sp=10, w=200, h=120):
    return np.zeros((h, w), dtype=bool)


def put_sharp(a, x, y, sp):
    """세로획 둘 — 글리프 하나를 흉내 낸다."""
    h = int(sp * 1.0)
    for dx in (0, int(sp * 0.35)):
        a[int(y - h):int(y + h), x + dx:x + dx + 2] = True


sp = 10.0
st = Staff(40, sp)
half = sp / 2

# ① ♯ 3개를 자리에 찍으면 3으로 센다
a = canvas()
for i, (_n, step) in enumerate(KP.SHARPS[:3]):
    put_sharp(a, 30 + int(i * sp), st.lines[0] + step * half, sp)
assert KP.count(a, st, sp, 25, 120) == (0, 3), KP.count(a, st, sp, 25, 120)

# ② 아무것도 없으면 0
assert KP.count(canvas(), st, sp, 25, 120) == (0, 0)

# ③ **구간이 좁으면 세지 않는다** — 음자리표 뒤에 바로 박자표가 오는 경우.
#    뒤지면 음자리표 가장자리를 ♯으로 센다(실측 day2conti-2).
a2 = canvas()
put_sharp(a2, 26, st.lines[0], sp)
assert KP.count(a2, st, sp, 25, 30) == (0, 0)

# ④ **멀리 떨어진 잉크는 조표가 아니다** — 조표 글리프는 서로 붙어 있다.
#    울타리가 없으면 첫 음표를 조표로 센다(실측 day2sb-5: 4를 7로).
a3 = canvas()
put_sharp(a3, 30, st.lines[0], sp)
put_sharp(a3, 100, st.lines[0] + 3 * half, sp)     # 한참 뒤
assert KP.count(a3, st, sp, 25, 160) == (0, 1), KP.count(a3, st, sp, 25, 160)

print("ok — 조표를 자리와 순서로 센다")
