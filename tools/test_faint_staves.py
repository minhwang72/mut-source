"""옅은 회색 오선 — 표의 검은 가로줄을 오선으로 잡지 않는가(실측 wish0809-1)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from PIL import Image
import sheetcv as cv


def page(staff_gray: int) -> Image.Image:
    a = np.full((700, 800), 255, np.uint8)
    for y in range(40, 40 + 38 * 8, 38):            # 위쪽 세트리스트 표: 검은 줄 8개
        a[y:y + 2, 20:780] = 0
    for top in (420, 520, 620):                      # 오선 세 단: 간격 9px
        for k in range(5):
            a[top + 9 * k, 40:760] = staff_gray
    return Image.fromarray(a).convert("RGB")


def test_faint_staff_beats_table():
    _ink, st = cv.find_staves_best(page(200))
    assert len(st) == 3 and abs(cv.median_spacing(st) - 9) < 1


def test_dark_staff_unchanged():
    _ink, st = cv.find_staves_best(page(0))
    assert cv.median_spacing(st) < 38            # 진한 오선이면 원래 길로도 찾는다


if __name__ == "__main__":
    test_faint_staff_beats_table(); test_dark_staff_unchanged(); print("ok")
