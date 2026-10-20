"""붙임점 찾는 자리와 곡선 구분 — 실제 악보로 잰 값을 못박는다."""
import sys, os
import numpy as np
sys.path.insert(0, os.path.dirname(__file__))
import durations as D

# ① 탐색 자리가 **실제 악보 분포** 안에 있어야 한다.
#    실측 181개: 가로 중앙값 0.70칸, 5~95% 0.55~0.92.
#    합성으로 맞춘 옛 값(0.44~0.56)은 181개 중 6개만 덮었다.
src = open(os.path.join(os.path.dirname(__file__), "durations.py")).read()
assert "for ddx in (0.60, 0.70, 0.80, 0.90)" in src, "가로 탐색 자리가 실측 분포를 벗어났다"
assert "for dy in (0.0, -0.35, -0.6)" in src, "세로 탐색 자리가 실측 분포를 벗어났다"

SP = 18.0
R = max(2.0, SP * 0.55)
r = max(1.0, SP * 0.20)

def canvas():
    return np.full((120, 120), 250.0, dtype="float32")

# ② 작고 둥근 점은 점으로 본다
g = canvas()
yy, xx = np.ogrid[:120, :120]
g[(yy - 60) ** 2 + (xx - 60) ** 2 <= 3.5 ** 2] = 20.0
assert not D._wide(g, 60, 60, r, 250.0, 231.0, SP), "점을 선으로 봤다"

# ③ 가로로 이어진 선(이음줄)은 점이 아니다
g2 = canvas()
g2[57:63, 20:100] = 20.0
assert D._wide(g2, 60, 60, r, 250.0, 231.0, SP), "이음줄을 점으로 봤다"

# ④ 종이만 있으면 넓지 않다
assert not D._wide(canvas(), 60, 60, r, 250.0, 231.0, SP)

# ⑤ 도돌이표(세로로 점 두 개)는 여전히 걸러야 한다 — 위아래 둘 다 작은 점
g3 = canvas()
for cy in (60, 60 + int(SP)):
    g3[(yy - cy) ** 2 + (xx - 60) ** 2 <= 3.5 ** 2] = 20.0
assert D._twin(g3, 60, 60, r, R, 231.0, SP), "도돌이표를 못 걸렀다"

# ⑥ 아래가 이음줄이면 도돌이표가 아니다 — 진짜 붙임점을 버리면 안 된다
g4 = canvas()
g4[(yy - 60) ** 2 + (xx - 60) ** 2 <= 3.5 ** 2] = 20.0
g4[60 + int(SP) - 3:60 + int(SP) + 3, 20:100] = 20.0      # 아래로 지나는 곡선
assert not D._twin(g4, 60, 60, r, R, 231.0, SP), "이음줄을 도돌이표로 오인했다"

print("ok — 붙임점 자리 · 점/곡선 구분 · 도돌이표는 계속 거름")
