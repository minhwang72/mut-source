"""갈라져 나온 빔 상자를 한 묶음으로 잇는 규칙."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from durations import beam_runs, read_durations                 # noqa: E402

SP = 10.0


def beam(cls, x, w, y=60.0):
    return {"class": cls, "x": x, "w": w, "y": y, "h": 8.0}


def head(x, y=90.0):
    return {"class": "notehead_filled", "x": x, "w": 12.0, "y": y, "h": 9.0}


def test_runs_merge_touching():
    # 1겹 빔이 2겹 빔 앞에서 끊긴 모양 — 한 묶음이다
    runs = beam_runs([beam("beam1", 100, 27), beam("beam2", 126, 14)], SP)
    assert len(runs) == 1, runs
    assert (runs[0]["x0"], runs[0]["x1"]) == (100, 140)


def test_runs_keep_separate_groups():
    # 다른 묶음은 3칸 이상 떨어진다 — 잇지 않는다
    runs = beam_runs([beam("beam1", 100, 27), beam("beam1", 160, 27)], SP)
    assert len(runs) == 2, runs


def test_runs_do_not_merge_across_voices():
    # x 는 맞닿아도 높이가 다르면 다른 빔이다
    runs = beam_runs([beam("beam1", 100, 27, y=60),
                      beam("beam1", 126, 27, y=140)], SP)
    assert len(runs) == 2, runs


def test_pair_shares_a_group():
    # 끊긴 상자 양 끝의 두 음표가 **같은 묶음**이어야 빔이 그려진다
    boxes = [beam("beam1", 100, 27), beam("beam2", 126, 14),
             head(88), head(128)]
    out = read_durations(boxes, SP)
    gs = [h["beamGroup"] for h in out]
    assert gs[0] >= 0 and gs[0] == gs[1], out


if __name__ == "__main__":
    test_runs_merge_touching()
    test_runs_keep_separate_groups()
    test_runs_do_not_merge_across_voices()
    test_pair_shares_a_group()
    print("ok")
