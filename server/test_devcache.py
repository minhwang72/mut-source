"""개발 LLM 캐시는 **개발 통로에서만** 설치되고, 두 번째 호출은 공짜다."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))


def test_only_in_dev():
    import serve
    # 배포 모양: MUTE_DEV_DIR 이 없고 origin 이 있다
    serve.DEV_DIR = ""
    serve.STATE["origin"] = "https://conti.eungming.com"
    assert serve.dev_enabled() is False
    serve.DEV_DIR = "/tmp/x"
    assert serve.dev_enabled() is False          # origin 이 있으면 안 켜진다
    serve.STATE["origin"] = None
    serve.STATE["host"] = "0.0.0.0"
    assert serve.dev_enabled() is False          # 바깥에 열려 있으면 안 켜진다
    serve.STATE["host"] = "127.0.0.1"
    assert serve.dev_enabled() is True


def test_second_call_is_free():
    with tempfile.TemporaryDirectory() as d:
        os.environ["MUTE_DEV_CACHE"] = d
        import importlib
        import devcache
        importlib.reload(devcache)
        import readcounts as RC
        calls = []

        class Img:                                # tobytes 만 있으면 된다
            def tobytes(self):
                return b"sheet"

        RC.read_page = lambda img, *a, **k: (calls.append(1), {"systems": [1]})[1]
        devcache.install()
        assert RC.read_page(Img()) == {"systems": [1]}
        assert RC.read_page(Img()) == {"systems": [1]}
        assert len(calls) == 1, f"두 번 불렀다: {calls}"
        del os.environ["MUTE_DEV_CACHE"]


if __name__ == "__main__":
    test_second_call_is_free()
    test_only_in_dev()
    print("ok")
