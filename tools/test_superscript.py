"""
코드 위첨자(⁷·²)가 상자에 들어오는가.

왜: 위첨자는 본체 **위에 얹혀** 세로로 안 겹친다. 겹침 50% 규칙에서
떨어져 나가면 혼자서는 최소 높이에 못 미쳐 버려지고, LLM 은 7 없는 코드를
읽는다 — 실측: 'Gm7' → 'Gm', 'F2' → 'F' (내마음다해 1단).
좌표는 그 악보에서 그대로 뜬 것이다(오선간격 6px).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sheetcv import Box, merge_horizontal

SP = 6
GAP = max(2, int(SP * 0.9))          # 5
STACK = max(1, round(SP * 0.6))      # 4
MIN_H = max(4, round(SP * 1.6))      # 10


def boxes(*t):
    return [Box(x, y, w, h) for x, y, w, h in t]


def merged(bs):
    return [b for b in merge_horizontal(bs, GAP, stack_gap=STACK) if b.h >= MIN_H]


# ── Gm7 : 7 이 본체 바로 위
g = merged(boxes((153, 74, 20, 10), (156, 71, 7, 3), (169, 68, 4, 8)))
assert len(g) == 1, f"Gm7 이 {len(g)}조각으로 남았다"
assert g[0].y == 68 and g[0].h == 16, f"7 이 빠졌다: y{g[0].y} h{g[0].h}"

# ── F2 : 2 가 오른쪽 위로 비낌 (세로 겹침 4px, 50% 기준 4.5px 를 못 넘는다)
f = merged(boxes((195, 72, 7, 12), (204, 67, 5, 9)))
assert len(f) == 1, f"F2 가 {len(f)}조각으로 남았다"
assert f[0].w == 14 and f[0].y == 67, f"2 가 빠졌다: y{f[0].y} w{f[0].w}"

# ── 같은 높이로 붙은 글자는 원래 규칙대로 한 코드다 (Fsus 의 F+s+u+s)
two = merged(boxes((195, 72, 7, 12), (204, 72, 7, 12)))
assert len(two) == 1, "같은 글자열이 쪼개졌다"

# ── **오른쪽 아래**로 비낀 작은 조각은 위첨자가 아니다.
#    가사 꼬리·이음줄 잔여물이 여기로 들어오면 상자가 아래로 늘어난다.
low = merge_horizontal(boxes((195, 72, 7, 12), (204, 80, 5, 9)), GAP, stack_gap=STACK)
assert len(low) == 2, f"아래로 비낀 조각을 위첨자로 삼켰다: {len(low)}"

# ── 멀리 떨어진 건 안 합친다
far = merged(boxes((195, 72, 7, 12), (240, 67, 5, 9), (240, 72, 8, 12)))
assert len(far) == 2, f"거리를 무시하고 합쳤다: {len(far)}"

# ── stack_gap 0 이면 옛 동작 그대로 (다른 호출자를 안 건드린다)
old = [b for b in merge_horizontal(boxes((153, 74, 20, 10), (169, 68, 4, 8)), GAP)
       if b.h >= MIN_H]
assert len(old) == 1 and old[0].h == 10, "stack_gap 없이 동작이 바뀌었다"

print("ok")
