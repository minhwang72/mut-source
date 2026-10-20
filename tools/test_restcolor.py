"""손으로 적은 유채색 쉼표는 인쇄된 쉼표로 받지 않는다 — 머리와 같은 규칙."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np                                            # noqa: E402
import evaldet as E                                           # noqa: E402


def _page(color):
    """흰 바탕에 작은 표시 하나. color 가 빨강이면 손글씨다."""
    a = np.full((60, 60, 3), 255, dtype="uint8")
    a[20:40, 20:32] = color
    return a


def test_red_mark_is_colored():
    assert E.colored(_page((200, 20, 20)), 20, 20, 12, 20) is True


def test_black_mark_is_not():
    assert E.colored(_page((20, 20, 20)), 20, 20, 12, 20) is False


def test_rest_filter_is_wired_the_same_as_heads():
    """쉼표를 고르는 줄에도 colored 가 걸려 있어야 한다."""
    src = Path(E.__file__).read_text()
    head = src.index('heads = sorted(')
    rest = src.index('rests = sorted(')
    for name, i in (("머리", head), ("쉼표", rest)):
        chunk = src[i:i + 600]
        assert "colored(rgb" in chunk, f"{name} 줄에 색 필터가 없다"
        assert "wash or not" in chunk, f"{name} 줄에 형광펜 예외가 없다"


if __name__ == "__main__":
    test_red_mark_is_colored()
    test_black_mark_is_not()
    test_rest_filter_is_wired_the_same_as_heads()
    print("ok")
