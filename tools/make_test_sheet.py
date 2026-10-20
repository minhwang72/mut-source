#!/usr/bin/env python3
"""
합성 리드시트 생성기 — 파이프라인 검증용.

실제 고해상도 악보를 구하기 전에 오선 제거·조표 교체·멜로디 이동을
검증하려면 "오선 간격이 충분한 악보"가 필요하다. 여기서 만든다.

정답을 알고 만들기 때문에 이동 후 음높이가 맞는지 자동 검증할 수 있다.
실제 악보의 지저분함(스캔 잡티·기울어짐·손글씨)은 재현하지 않는다 —
그건 실제 파일로만 검증된다.

    python3 tools/make_test_sheet.py -o test.png --spacing 16
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

GLYPH_FONTS = [
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/Apple Symbols.ttf",
]
TEXT_FONTS = ["/System/Library/Fonts/Supplemental/Arial Bold.ttf"]
# 가사는 한글이라 Arial로는 두부 박스가 나온다
KR_FONTS = ["/System/Library/Fonts/AppleSDGothicNeo.ttc",
            "/System/Library/Fonts/Supplemental/AppleGothic.ttf"]

# 높은음자리표 기준: 5선(맨 위)을 0으로 한 반칸 단위. 아래로 갈수록 +
# F5=0 E5=1 D5=2 C5=3 B4=4 A4=5 G4=6 F4=7 E4=8 D4=9 C4=10
STEP_NAME = {0: "F5", 1: "E5", 2: "D5", 3: "C5", 4: "B4", 5: "A4",
             6: "G4", 7: "F4", 8: "E4", 9: "D4", 10: "C4", 11: "B3"}

FLAT_STEPS = [4, 1, 5, 2, 6, 3, 7]
SHARP_STEPS = [0, 3, -1, 2, 5, 1, 4]

# 데모용 예시 가사 — 음절 단위로 음표 아래에 하나씩 붙인다.
# 저작권 없는 임의 문구.
LYRICS = [
    list("샘플악보입니다키를"),
    list("바꿔보면코드와멜로"),
    list("디가함께따라옵니다"),
]


def font(paths: list[str], size: int) -> ImageFont.FreeTypeFont:
    for p in paths:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    raise SystemExit("폰트를 찾지 못했습니다.")


class SheetBuilder:
    def __init__(self, spacing: int = 16, systems: int = 3, width: int | None = None):
        self.sp = spacing
        self.n_systems = systems
        self.staff_h = spacing * 4
        self.margin_x = spacing * 3
        # 단 간격은 이 모두를 담아야 한다: 오선(4칸) + 가사(오선 아래 3.2칸
        # + 글자 높이) + 다음 단 코드 줄(최고음 위). 좁으면 코드가 앞 단 가사와
        # 겹치고, 가사 복원이 옮겨진 코드·음표를 원본 화소로 덮어써 조각이
        # 남는다(실측: 코드 줄을 올린 뒤 조각이 나타났다).
        self.system_gap = spacing * 16
        self.width = width or spacing * 100
        self.height = spacing * 5 + systems * self.system_gap + spacing * 6
        self.img = Image.new("RGB", (self.width, self.height), "white")
        self.d = ImageDraw.Draw(self.img)
        self.truth: list[dict] = []

    # ---------------------------------------------------------- 기하
    def staff_top(self, i: int) -> int:
        return self.sp * 5 + i * self.system_gap

    def step_y(self, i: int, step: float) -> float:
        """5선(맨 위)을 0으로 한 반칸 위치 → y좌표"""
        return self.staff_top(i) + step * (self.sp / 2.0)

    @property
    def line_thickness(self) -> int:
        return max(1, round(self.sp / 8))

    # ---------------------------------------------------------- 그리기
    def draw_staff(self, i: int) -> None:
        t = self.line_thickness
        for k in range(5):
            y = self.staff_top(i) + k * self.sp
            self.d.rectangle(
                [self.margin_x, y, self.width - self.sp * 2, y + t - 1], fill="black"
            )

    def draw_clef(self, i: int) -> int:
        """
        진짜 높은음자리표 글리프(U+1D11E 𝄞)를 그린다.
        Apple Symbols에 실제 글리프가 있다 — Arial Unicode 등에는 두부 박스가 나온다.

        기준: G 클레프의 소용돌이 중심이 2선(G4)에 와야 한다.
        """
        f = font(["/System/Library/Fonts/Apple Symbols.ttf"], int(self.sp * 7.4))
        glyph = "\U0001D11E"
        l, t, r, b = f.getbbox(glyph)
        x = self.margin_x + self.sp // 2
        # 글리프 높이가 오선 5줄 + 위아래 여유를 덮도록 위치를 맞춘다
        y = self.staff_top(i) - int(self.sp * 1.9) - t
        self.d.text((x - l, y), glyph, fill="black", font=f)
        return x + (r - l) + self.sp // 2

    def draw_keysig(self, i: int, x: int, fifths: int) -> int:
        if fifths == 0:
            return x
        glyph = "♯" if fifths > 0 else "♭"
        steps = (SHARP_STEPS if fifths > 0 else FLAT_STEPS)[: abs(fifths)]
        f = font(GLYPH_FONTS, int(round(self.sp * 2.2 * 1.35)))
        l, t, r, b = f.getbbox(glyph)
        gh = b - t
        adv = max(3, int(round((r - l) * 0.95)))
        for s in steps:
            cy = self.step_y(i, s)
            self.d.text((x - l, cy - gh / 2 - t), glyph, fill="black", font=f)
            x += adv
        return x + self.sp // 3

    def draw_timesig(self, i: int, x: int, text: tuple[str, str]) -> int:
        f = font(TEXT_FONTS, int(self.sp * 2.1))
        for k, ch in enumerate(text):
            l, t, r, b = f.getbbox(ch)
            cy = self.step_y(i, 2 if k == 0 else 6)
            self.d.text((x - l, cy - (b - t) / 2 - t), ch, fill="black", font=f)
        return x + int(self.sp * 1.8)

    def draw_barline(self, i: int, x: int) -> None:
        t = self.line_thickness
        self.d.rectangle(
            [x, self.staff_top(i), x + t - 1, self.staff_top(i) + self.staff_h],
            fill="black",
        )

    def draw_note(self, i: int, x: int, step: float, kind: str) -> None:
        """kind: 'quarter'(속 찬+기둥) | 'half'(속 빈+기둥) | 'whole'(속 빈)"""
        cy = self.step_y(i, step)
        rx = self.sp * 0.62
        ry = self.sp * 0.46
        box = [x - rx, cy - ry, x + rx, cy + ry]
        if kind == "quarter":
            self.d.ellipse(box, fill="black")
        else:
            # 실제 조판에서 속 빈 음표의 테두리는 오선보다 훨씬 굵다.
            # 오선과 같은 두께로 그리면 오선 제거 때 구별되지 않아 부서진다.
            self.d.ellipse(box, outline="black",
                           width=max(2, round(self.line_thickness * 2.5)))
        if kind in ("quarter", "half"):
            t = max(1, round(self.sp / 9))
            up = step > 4
            sx = x + rx - t if up else x - rx
            sy0 = cy - self.sp * 2.6 if up else cy
            sy1 = cy if up else cy + self.sp * 2.6
            self.d.rectangle([sx, sy0, sx + t - 1, sy1], fill="black")
        # 오선 밖이면 덧줄
        if step < 0:
            for s in range(0, int(step) - 1, -2):
                y = self.step_y(i, s)
                self.d.rectangle([x - rx * 1.6, y, x + rx * 1.6, y + self.line_thickness - 1],
                                 fill="black")
        if step > 8:
            for s in range(10, int(step) + 1, 2):
                y = self.step_y(i, s)
                self.d.rectangle([x - rx * 1.6, y, x + rx * 1.6, y + self.line_thickness - 1],
                                 fill="black")
        self.truth.append({"system": i, "x": x, "step": step, "kind": kind,
                           "pitch": STEP_NAME.get(int(step), f"step{step}")})

    def draw_chord(self, i: int, x: int, text: str,
                   min_step: float = 0.0) -> dict:
        # 실측 비율에 맞춘다: 실제 악보의 코드 심볼 높이는 오선 간격의 2~3배다
        # (오선간격 6px 악보에서 박스 높이 12~18px). 작게 그리면 검출기의
        # 높이 판별자에 걸러진다 — 검출기가 아니라 이쪽을 맞춰야 한다.
        f = font(TEXT_FONTS, int(self.sp * 2.9))
        l, t, r, b = f.getbbox(text)
        # 코드 줄은 **최고음 위**에 놓는다. 실제 리드시트는 코드 심볼이
        # 음표와 겹치지 않는다 — 겹치면 코드를 지울 때 음표 머리를 같이
        # 지우게 되고, 화소만 보고 둘을 가릴 방법이 없다.
        top = self.staff_top(i) - int(self.sp * 3.2)
        if min_step < 0:
            top -= int(round(abs(min_step) * (self.sp / 2.0) + self.sp * 0.6))
        y = top
        self.d.text((x - l, y), text, fill="black", font=f)
        return {"text": text, "box": {"x": x, "y": y + t, "w": r - l, "h": b - t},
                "confidence": 1.0}

    def draw_lyrics(self, i: int, syllables: list[str], note_xs: list[int]) -> None:
        """
        음절을 음표 아래에 하나씩 붙인다.

        크기는 실측에 맞춘다: 실제 악보의 한글 음절은 오선 간격의 1.5~1.9배
        높이다(오선간격 6.5px 악보에서 10~12px). 그보다 작게 그리면
        "가사가 안 들어간 것처럼" 보인다 — 실제로 그런 지적을 받았다.
        """
        if not note_xs:
            return
        f = font(KR_FONTS, int(self.sp * 2.7))
        # 실제 조판은 가사를 기둥 아래에 둔다. 겹치면 이조 때 기둥 조각이
        # 가사 위에 남는다(실측).
        y = self.staff_top(i) + self.staff_h + int(self.sp * 3.2)
        for k, x in enumerate(note_xs):
            if k >= len(syllables):
                break
            t = syllables[k]
            w = self.d.textlength(t, font=f)
            self.d.text((x - w / 2, y), t, fill="black", font=f)


def build(spacing: int, key_fifths: int, systems: int = 3,
          width: int | None = None) -> tuple[Image.Image, dict]:
    b = SheetBuilder(spacing=spacing, systems=systems, width=width)
    systems_out = []

    # 각 단: 음자리표 + 조표 + (0단만 박자표) + 마디 4개
    plan = [
        # (코드, [(step, kind), ...])
        [("Bb", [(8, "quarter"), (6, "quarter"), (4, "half")]),
         ("Gm7", [(5, "quarter"), (3, "quarter"), (2, "half")]),
         ("F2", [(4, "whole")]),
         ("Bb", [(6, "quarter"), (4, "quarter"), (2, "half")])],
        [("Ebmaj7", [(1, "quarter"), (0, "quarter"), (-1, "half")]),
         ("Eb/F", [(3, "half"), (5, "half")]),
         ("Fsus", [(7, "quarter"), (9, "quarter"), (10, "half")]),
         ("Bb/D", [(4, "whole")])],
        [("D7+5", [(2, "quarter"), (4, "quarter"), (6, "quarter"), (8, "quarter")]),
         ("Gm7", [(5, "half"), (3, "half")]),
         ("Cm7", [(0, "quarter"), (2, "quarter"), (4, "half")]),
         ("Bb", [(4, "whole")])],
    ]

    # 요청한 단 수만큼 마디 묶음을 되풀이한다
    plan = [plan[i % len(plan)] for i in range(systems)]

    for i, measures in enumerate(plan):
        b.draw_staff(i)
        x = b.draw_clef(i)
        x = b.draw_keysig(i, x, key_fifths)
        if i == 0:
            x = b.draw_timesig(i, x, ("4", "4"))
        head_end = x

        chords = []
        note_xs = []
        # 이 단의 최고음(step이 작을수록 높다) — 코드 줄 높이를 정한다
        min_step = min(st for _, ns in measures for st, _ in ns)
        bar_w = (b.width - b.sp * 2 - head_end) // len(measures)
        for mi, (chord, notes) in enumerate(measures):
            mx = head_end + mi * bar_w
            chords.append(b.draw_chord(i, mx + spacing // 2, chord, min_step))
            step_w = bar_w // (len(notes) + 1)
            for ni, (step, kind) in enumerate(notes):
                nx = mx + step_w * (ni + 1)
                b.draw_note(i, nx, step, kind)
                note_xs.append(nx)
            b.draw_barline(i, mx + bar_w - b.sp // 2)
        b.draw_lyrics(i, LYRICS[i % len(LYRICS)], note_xs)

        systems_out.append({
            "index": i, "page": 0,
            "staffTop": b.staff_top(i),
            "staffBottom": b.staff_top(i) + b.staff_h,
            "headEnd": head_end,
            "chords": chords,
        })

    extraction = {
        "meta": {"title": "합성 검증 악보", "key": "Bb", "timeSignature": "4/4",
                 "pageCount": 1},
        "imageSize": {"w": b.width, "h": b.height},
        "systems": systems_out,
        "_truthNotes": b.truth,
        "_spacing": spacing,
    }
    return b.img, extraction


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--extraction", required=True)
    ap.add_argument("--spacing", type=int, default=16)
    ap.add_argument("--fifths", type=int, default=-2, help="원조성 조표 (Bb=-2)")
    ap.add_argument("--systems", type=int, default=3, help="단 수")
    ap.add_argument("--width", type=int, help="이미지 폭(px). 생략 시 간격×100")
    args = ap.parse_args()

    img, ex = build(args.spacing, args.fifths, args.systems, args.width)
    img.save(args.out)
    with open(args.extraction, "w", encoding="utf-8") as f:
        json.dump(ex, f, ensure_ascii=False, indent=2)
    print(f"{args.out}  {img.size}  오선간격 {args.spacing}px  "
          f"음표 {len(ex['_truthNotes'])}개  코드 "
          f"{sum(len(s['chords']) for s in ex['systems'])}개")


if __name__ == "__main__":
    main()
