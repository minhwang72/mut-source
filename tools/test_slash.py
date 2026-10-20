#!/usr/bin/env python3
"""
슬래시 보정 회귀 시험. `python3 tools/test_slash.py`

이 시험이 있는 이유: 처음 만든 정규식이 `Bb`(B♭)를 `B/B`로 바꿨다.
근음의 임시표가 선택적이라 `b`가 베이스음으로 잡힌 것이다 — **내림표 코드
전부가 깨지는** 버그였다. 다시 그러지 않도록 못 박는다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from read_chords import repair_slash  # noqa: E402

# (입력, 기대) — None이면 건드리지 않아야 한다
CASES = [
    # 되살려야 하는 것
    ("Ebf", "Eb/F"), ("Bbd", "Bb/D"), ("Ba", "B/A"), ("Ce", "C/E"),
    # 실제로 나온 형태 — 베이스음이 대문자로 붙어 왔다 (웹에서 재현)
    ("EbF", "Eb/F"), ("BbD", "Bb/D"),
    ("Fa", "F/A"), ("F#a", "F#/A"), ("Ebfb", "Eb/Fb"),
    # **절대 건드리면 안 되는 것** — 임시표가 붙은 근음
    ("Bb", None), ("Gb", None), ("Ab", None), ("Db", None), ("Eb", None),
    ("F#", None), ("C#", None), ("Bbb", None),
    # 성질 표기가 있는 것
    ("Gm7", None), ("Ebmaj7", None), ("Fsus", None), ("F2", None),
    ("D7+5", None), ("Am", None), ("Bdim", None), ("Cadd9", None),
    ("F#m7b5", None), ("Cm7", None), ("Ebfr", None),
    # 이미 슬래시가 있는 것
    ("Eb/F", None), ("Bb/D", None),
    # 코드가 아닌 것
    ("", None), ("melody", None), ("7", None),
]


def main() -> None:
    bad = []
    for text, want in CASES:
        got = repair_slash(text)
        if got != want:
            bad.append((text, want, got))
    for text, want, got in bad:
        print(f"  ✗ {text!r}: 기대 {want!r} · 실제 {got!r}")
    print(f"슬래시 보정 {len(CASES) - len(bad)}/{len(CASES)} 통과")
    raise SystemExit(1 if bad else 0)


if __name__ == "__main__":
    main()
