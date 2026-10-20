"""오선 위 띠를 열 단위로 끊는 규칙. `gap` 보다 멀면 다른 표시다."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np                                            # noqa: E402
from serve import _ink_runs                                   # noqa: E402


def cols(spec: str):
    return np.array([c == "#" for c in spec])


def test_runs():
    # gap 2: 세 칸 띈 것은 끊고, 한 칸 띈 것은 한 덩어리로 둔다
    assert _ink_runs(cols("##.##....###"), 2) == [[0, 5], [9, 12]]
    # 한 칸짜리 점은 버린다 — 오선 찌꺼기지 표시가 아니다
    assert _ink_runs(cols("#....##"), 2) == [[5, 7]]
    # 끝에서 끝난 구간도 닫는다
    assert _ink_runs(cols("....###"), 2) == [[4, 7]]
    assert _ink_runs(cols("......"), 2) == []
    # "Verse 1" 상자(붙어 있다) 옆 손글씨(떨어져 있다)
    assert _ink_runs(cols("#########...##"), 2) == [[0, 9], [12, 14]]


if __name__ == "__main__":
    test_runs()
    print("ok")
