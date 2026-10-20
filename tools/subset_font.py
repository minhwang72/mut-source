#!/usr/bin/env python3
"""
**폰트를 둘로 쪼갠다 — 화면에 쓰는 글자와 나머지.**

Pretendard Variable 전체는 2.0MB 다. 한글 음절 11,172자를 다 담고 있어서인데,
화면 문구에 실제로 쓰인 음절은 **702자**뿐이다. 그런데 첫 로딩에서 2MB 를
통째로 받느라 1초가 걸리고, 그동안 대체 글꼴로 그려졌다가 바뀌며 화면이 튄다.

`unicode-range` 로 두 벌을 선언하면 브라우저가 **그 범위의 글자가 실제로
쓰일 때만** 내려받는다. 평소에는 작은 쪽만 받고, 사용자가 드문 음절이 든
이름을 넣었을 때만 큰 쪽이 따라온다.

  ui  소스(html·js·py)에 적힌 글자 + 라틴·숫자·부호
  ko  나머지 한글 음절 — 사용자 입력 대비

사용자 가사는 원본 픽셀을 오려 붙이므로 폰트와 무관하다.

  python tools/subset_font.py      # 두 벌을 만들고 CSS 에 넣을 범위를 찍는다
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "web/vendor/PretendardVariable.woff2"
UI = ROOT / "web/vendor/pretendard-ui.woff2"
KO = ROOT / "web/vendor/pretendard-ko.woff2"
CSS = ROOT / "web/vendor/pretendard.css"
SCAN = ["web/index.html", "web/app.js", "web/redraw.js", "web/fixbeats.js",
        "web/verovio-page.js", "web/sheet-render.js", "web/service.js",
        "web/musicxml.js", "web/source-pitch.js",
        "server/serve.py", "server/local_reader.py", "server/jobs.py",
        "server/db.py"]
SYMBOLS = (
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    " !\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"
    "·…—–‘’“”₩€°±×÷→←↑↓✓△▲□■○●♩♪♫♭♯𝄽𝄾"
)
HANGUL = range(0xAC00, 0xD7A4)


def used() -> set[str]:
    out: set[str] = set(SYMBOLS)
    for rel in SCAN:
        p = ROOT / rel
        if p.exists():
            out |= set(p.read_text(encoding="utf-8", errors="ignore"))
    return {c for c in out if c == " " or (c.isprintable() and not c.isspace())}


def ranges(codes: list[int]) -> str:
    """정렬된 코드포인트를 `U+AC00-AC02,U+AC05` 꼴로 묶는다."""
    out, i = [], 0
    while i < len(codes):
        j = i
        while j + 1 < len(codes) and codes[j + 1] == codes[j] + 1:
            j += 1
        out.append(f"U+{codes[i]:04X}" if i == j
                   else f"U+{codes[i]:04X}-{codes[j]:04X}")
        i = j + 1
    return ",".join(out)


def cut(chars: set[str], dst: Path) -> int:
    from fontTools import subset
    opts = subset.Options()
    opts.flavor = "woff2"
    opts.layout_features = ["kern", "liga", "calt", "ccmp", "locl"]
    opts.name_IDs = ["*"]
    opts.notdef_outline = True
    font = subset.load_font(str(SRC), opts)
    s = subset.Subsetter(options=opts)
    s.populate(text="".join(sorted(chars)))
    s.subset(font)
    subset.save_font(font, str(dst), opts)
    return dst.stat().st_size


def main() -> None:
    if not SRC.exists():
        sys.exit(f"원본 폰트가 없습니다: {SRC}")
    ui = used()
    rest = {chr(c) for c in HANGUL} - ui
    a, b = cut(ui, UI), cut(rest, KO)
    before = SRC.stat().st_size
    print(f"ui  {len(ui):>6,}자  {a/1024:>7,.0f}KB  {UI.name}")
    print(f"ko  {len(rest):>6,}자  {b/1024:>7,.0f}KB  {KO.name}")
    print(f"원본 {before/1024:,.0f}KB → 평소 받는 양 {a/1024:,.0f}KB "
          f"({a/before:.0%})")
    # **CSS 도 여기서 쓴다.** 범위를 손으로 붙이면 폰트를 다시 깎을 때
    # 조용히 어긋난다 — 글자가 빠져도 대체 글꼴로 그려지니 안 보인다.
    css = CSS.parent / CSS.name
    css.write_text(
        "/* tools/subset_font.py 가 만든다 — 직접 고치지 말 것. */\n"
        "@font-face {\n"
        '  font-family: "Pretendard Variable"; font-weight: 300 800;\n'
        "  font-display: swap;\n"
        f'  src: url("{UI.name}") format("woff2-variations");\n'
        f"  unicode-range: {ranges(sorted(ord(c) for c in ui))};\n"
        "}\n"
        "/* 사용자가 입력한 이름에만 쓰이는 나머지 음절 — 그 글자가 화면에\n"
        "   실제로 나올 때만 브라우저가 내려받는다. */\n"
        "@font-face {\n"
        '  font-family: "Pretendard Variable"; font-weight: 300 800;\n'
        "  font-display: swap;\n"
        f'  src: url("{KO.name}") format("woff2-variations");\n'
        f"  unicode-range: {ranges(sorted(ord(c) for c in rest))};\n"
        "}\n", encoding="utf-8")
    print(f"\nCSS 작성: {css.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
