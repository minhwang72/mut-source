"""label_build.build_measure — 쉼표를 마디 안에서 왼쪽부터 고르는지."""
import sys
sys.path[:0] = ["eval"]
from label_build import build_measure, units


def box(cls, x, conf=0.5, y=100):
    return {"class": cls, "x": x, "y": y, "w": 8, "h": 8, "conf": conf}


def test_two_rests_keep_order_and_stay_inside():
    sp, x0, x1 = 10, 0, 200
    head = {"duration": "eighth", "head": {"x": 150, "y": 100, "w": 10, "h": 8}}
    cands = [box("rest_half", 40, 0.3), box("rest_8th", 40, 0.2),   # 같은 자리 겹친 후보
             box("rest_8th", 90, 0.9),                              # 점수 높은 오른쪽 쉼표
             box("rest_whole", 198, 0.95)]                          # 세로줄에 붙은 헛것
    out = build_measure(units(["r2", "r8", "8"]), [head], cands, x0, x1, sp, 80, 120)
    rests = [(b["class"], b["x"]) for b in out if b["class"].startswith("rest")]
    assert rests == [("rest_half", 40), ("rest_8th", 90)], rests


if __name__ == "__main__":
    test_two_rests_keep_order_and_stay_inside(); print("ok")
