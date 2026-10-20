"""
버려진 쉼표를 **모자란 마디에서만** 되살린다.

실측 근거(day2sb-1 단4 마디3): 원본은 ♪ + ♩. + 2분쉼표인데, 2분쉼표가
신뢰도 0.18 로 보였고 LLM 이 그 단 쉼표를 4개라 세는 바람에 버려졌다.
그 마디는 2박이 모자란 채 fit_page 로 넘어가 **음표를 늘려** 메웠다 —
2박 침묵이 3박 지속음이 됐는데 합은 4박이라 게이트가 통과시켰다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evaldet as E                                           # noqa: E402


class FakeBoxes:
    def __init__(self, rows):
        self.xyxy = type("T", (), {"tolist": lambda s: [r[0] for r in rows]})()
        self.cls = type("T", (), {"tolist": lambda s: [r[1] for r in rows]})()
        self.conf = type("T", (), {"tolist": lambda s: [r[2] for r in rows]})()


def test_dropped_rest_is_kept_as_spare():
    """개수가 찼어도 버린 쉼표는 spare 로 남는다 — 그게 없으면 되살릴 수 없다."""
    names = {0: "notehead_filled", 1: "rest_half", 2: "clef_g"}
    # 쉼표 둘: 하나는 고신뢰, 하나는 0.18. 기대 개수는 1 이라 뒤엣것이 버려진다.
    rows = [([100, 50, 112, 62], 0, 0.95),
            ([200, 40, 214, 48], 1, 0.80),
            ([400, 40, 414, 48], 1, 0.18)]

    class R:
        names = {0: "notehead_filled", 1: "rest_half", 2: "clef_g"}
        boxes = FakeBoxes(rows)

    class Model:
        def predict(self, *a, **k):
            return [R()]

    import sheetcv as cv
    from PIL import Image
    img = Image.new("L", (600, 200), 255)
    # 오선이 없으면 일찍 빠져나간다 — 가짜 오선을 그려 넣는다
    px = img.load()
    for y in (40, 50, 60, 70, 80):
        for x in range(20, 580):
            px[x, y] = 0
    _ink, staves = cv.find_staves_best(img)
    if not staves:
        print("  (오선 검출이 안 돼 건너뜀)")
        return
    boxes, meta = E.detect_guided(Model(), img, [1], expect_rests=[1])
    spare = [c for s in meta["spare"] for c in s]
    assert any(c["class"] == "rest_half" and c["conf"] < 0.2 for c in spare), (
        f"버린 쉼표가 spare 에 없다: {spare}")


if __name__ == "__main__":
    test_dropped_rest_is_kept_as_spare()
    print("ok")
