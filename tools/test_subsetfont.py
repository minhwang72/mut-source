"""코드포인트를 CSS unicode-range 로 묶는 규칙."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from subset_font import ranges                                 # noqa: E402


def test_single_and_run():
    assert ranges([0x41]) == "U+0041"
    assert ranges([0x41, 0x42, 0x43]) == "U+0041-0043"


def test_gap_splits():
    assert ranges([0x41, 0x42, 0x50]) == "U+0041-0042,U+0050"


def test_hangul_scatter():
    # 떨어진 음절은 따로, 붙은 것은 묶어서
    out = ranges([0xAC00, 0xAC01, 0xAC04, 0xD7A3])
    assert out == "U+AC00-AC01,U+AC04,U+D7A3", out


def test_empty():
    assert ranges([]) == ""


if __name__ == "__main__":
    test_single_and_run()
    test_gap_splits()
    test_hangul_scatter()
    test_empty()
    print("ok")
