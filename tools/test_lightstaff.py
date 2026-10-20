"""
연한 오선을 구제하는가.

왜: Otsu 는 전역 통계, Sauvola 는 국소 통계에 기대는데 150dpi PDF 의 오선은
1px 연회색이라 **둘 다 날린다.** 실측 wish0906-5 는 두 경로 모두 0단이었고
고정 문턱 200 에서 7단(정답)이 나왔다. 오선을 놓치면 그 아래 전부가 틀린다 —
가사 띠가 다음 단을 삼키고, 음표가 엉뚱한 단에 배정된다.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from PIL import Image
import prepare, sheetcv as cv

W, H, SP = 400, 300, 10


def sheet(gray: int) -> Image.Image:
    """
    오선 2단 + **진한 음표**를 그린다. gray 가 클수록 오선이 연하다.

    음표를 같이 그리는 게 핵심이다 — 오선만 있으면 Otsu 가 그 오선을
    기준으로 문턱을 잡아 연해도 잡아낸다. 진한 잉크가 함께 있어야 전역
    문턱이 그쪽으로 끌려가 연한 오선이 날아가는, 실제와 같은 상황이 된다.
    """
    a = np.full((H, W), 255, dtype="uint8")
    for top in (60, 180):
        for i in range(5):
            a[top + i * SP, 20:W - 20] = gray
        for x in range(40, W - 40, 30):          # 음표 머리 + 기둥 (새까맣다)
            a[top + 18:top + 24, x:x + 8] = 0
            a[top - 10:top + 20, x + 7:x + 9] = 0
    return Image.fromarray(a).convert("RGB")


dark, light = sheet(0), sheet(190)

# ── 진한 오선은 원래 경로가 찾는다 (구제가 필요 없다)
ink0 = cv.binarize_otsu(dark)
assert len(cv.find_staves(ink0)) == 2, "기준 이미지부터 안 잡힌다"

# ── 연한 오선은 Otsu 가 놓친다 → 구제가 살려야 한다
ink1 = cv.binarize_otsu(light)
before = cv.find_staves(ink1)
rep = {"steps": []}
_ink, after = prepare.rescue_light_staves(light, ink1, before, rep)
assert len(after) > len(before), f"연한 오선을 못 살렸다 ({len(before)} → {len(after)})"
assert len(after) == 2, f"단 수가 틀리다: {len(after)}"
assert rep.get("lightRescue"), "구제 기록이 없다 — 나중에 원인 추적을 못 한다"

# ── **이미 잘 찾았으면 건드리지 않는다.** 문턱을 올리면 잉크가 늘어
#    오검출이 생길 수 있으므로, 더 많이 찾을 때만 바꿔야 한다.
rep2 = {"steps": []}
ink2, keep = prepare.rescue_light_staves(dark, ink0, cv.find_staves(ink0), rep2)
assert len(keep) == 2 and not rep2.get("lightRescue"), "멀쩡한 결과를 바꿨다"
assert ink2 is ink0, "안 바꿔도 되는데 잉크 마스크를 갈아치웠다"

print("ok")
