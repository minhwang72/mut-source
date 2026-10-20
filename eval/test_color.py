"""색 필터가 **검은 음표는 남기고 유채색 표시만** 버리는가.

주의: 주변에 검은 잉크(오선)가 있어야 비교가 성립한다. 순백 배경만 두면
유채색 상자가 주변 창에서도 가장 어두운 화소가 되어 차이가 0이 된다 —
실제 악보에는 늘 오선이 있으므로 테스트도 그렇게 만든다.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import numpy as np
import evaldet as E

W = H = 40


def scene(ink, bg=(255, 255, 255), line=(0, 0, 0)):
    """3×3 창: 배경 + 가로 오선 두 줄 + 가운데 상자."""
    a = np.full((H * 3, W * 3, 3), bg, dtype=np.uint8)
    a[H // 2, :] = line                      # 상자 위쪽 오선
    a[H * 2 + H // 2, :] = line              # 아래쪽 오선
    a[H:H * 2, W:W * 2] = ink
    return a


assert not E.colored(scene((10, 10, 10)), W, H, W, H), "검은 머리를 버렸다"
assert E.colored(scene((220, 20, 20)), W, H, W, H), "빨간 글자를 못 버렸다"
assert E.colored(scene((40, 120, 235)), W, H, W, H), "파란 손글씨를 못 버렸다"

# **형광펜 띠**: 배경·오선·잉크가 모두 청록으로 물들었다 → 남겨야 한다
assert not E.colored(scene((10, 40, 40), bg=(120, 230, 230), line=(20, 90, 90)),
                     W, H, W, H), "형광펜 아래 진짜 음표를 버렸다"

# 경계: 빈 상자·이미지 밖·색 없음에서 죽지 않는다
assert not E.colored(scene((220, 20, 20)), -50, -50, 0, 0)
assert not E.colored(None, 0, 0, 10, 10)
print("ok")
