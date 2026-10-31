"""
**코드를 한 번 더 읽어 맞을 때만 믿는다** — 음표의 homr 교차 검증과 같은 생각.

첫 판독(read_chords)은 검출기가 자른 조각을 하나씩 읽는다. 그래서 검출기가
놓친 코드(손글씨·회색 상자)는 아예 없고, 조각에 가사 글자가 섞이면 'Asus2'
처럼 엉뚱한 코드가 된다. 과금 장 26장 대조에서 13장이 이걸로 틀렸다(2026-10-31).

두 번째 판독은 **단마다 오선 위 띠를 통째로** 보여 주고 왼쪽부터 순서대로
적게 한다. 단별로 둘을 견주어 다르면 그 단을 확인 필요로 돌린다 — 고치지는
않는다(어느 쪽이 맞는지, 어느 마디인지 모른다).
"""
from __future__ import annotations

import re
import sys

from pydantic import BaseModel, Field

MODEL = "claude-sonnet-5-5"
REVIEW = "코드가 두 판독에서 다릅니다 — 원본 확인 필요"


class SystemChords(BaseModel):
    system: int = Field(description="띠 왼쪽 빨간 번호")
    chords: list[str] = Field(description="그 띠의 코드 심볼, 왼쪽부터 순서대로")


class PageChords(BaseModel):
    systems: list[SystemChords]


PROMPT = """이 이미지는 악보의 단(오선 한 줄)마다 **오선 위쪽 띠**를 잘라 위에서부터 쌓은 것이다.
각 띠 왼쪽의 **빨간 숫자**가 단 번호다(코드가 아니다). 띠 아래쪽에 오선 윗부분이 조금 보인다.

띠 {n}개 전부에 대해, 그 단 위에 적힌 **코드 심볼을 왼쪽부터 순서대로** 적어라.

규칙:
- 보이는 대로 옮긴다. 올림표 `#`, 내림표 `b`. 예: Bb, Gm7, Ebmaj7, F#m7, Bb/D, Esus4, E7(sus4), D2/F#
- 분수코드 슬래시를 빠뜨리지 말 것(베이스음이 오른쪽 아래 작게 붙는다).
- 코드 둘이 붙어 있어도 따로 적는다(Esus4 E7 → 두 개).
- 손글씨·색깔 코드도 코드다. 괄호 안 대체 코드(예: `G/D(Em)`)는 괄호째 한 개로 적는다.
- **코드가 아닌 것은 빼라**: 가사, 연주 지시어(Fine, D.S., D.C., Coda, To Coda),
  구역 표시(A, B, C′ 같은 상자 글자), 템포, 마디 번호, 반복 괄호 번호(1., 2.).
- 코드가 없는 단은 빈 목록.

{n}개 단을 번호 순서대로 모두 반환하라."""


def strip_image(img, systems: list[dict]):
    """단마다 오선 위 띠를 잘라 번호를 붙여 쌓는다. (이미지, 단 번호 목록)."""
    from PIL import Image, ImageDraw
    import read_chords as RC
    crops, idx = [], []
    for i, g in enumerate(systems):
        sp = float(g.get("spacing") or 10)
        top = float(g["staffTop"])
        y0 = max(0, int(top - sp * 5))
        y1 = min(img.height, int(top + sp * 1.5))
        if y1 - y0 < sp:
            continue
        crops.append(img.crop((0, y0, img.width, y1)).convert("RGB"))
        idx.append(g.get("index", i))
    pad = 70
    W = max(c.width for c in crops) + pad
    H = sum(c.height + 8 for c in crops)
    out = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(out)
    font = RC.label_font(36)
    y = 0
    for c, k in zip(crops, idx):
        out.paste(c, (pad, y))
        d.text((6, y + c.height // 3), str(k + 1), fill=(220, 0, 0), font=font)
        d.line((0, y + c.height + 4, W, y + c.height + 4), fill=(180, 180, 180), width=2)
        y += c.height + 8
    # 너무 크면 줄인다 — 모델 입력 상한
    if out.width > 2400:
        k = 2400 / out.width
        out = out.resize((2400, max(1, int(out.height * k))))
    return out, idx


def read(strip, n: int, model: str = MODEL) -> list[SystemChords]:
    import base64
    import io

    import anthropic
    buf = io.BytesIO()
    strip.save(buf, format="PNG")
    b64 = base64.standard_b64encode(buf.getvalue()).decode()
    resp = anthropic.Anthropic().messages.parse(
        model=model, max_tokens=8000, thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
            {"type": "text", "text": PROMPT.format(n=n)}]}],
        output_format=PageChords)
    if resp.stop_reason == "refusal":
        raise RuntimeError("코드 재판독을 모델이 거절했습니다")
    u = resp.usage
    print(f"  코드 재판독 토큰 in {u.input_tokens} / out {u.output_tokens}", file=sys.stderr)
    return resp.parsed_output.systems


_SAME = [(r"[♭]", "b"), (r"[♯]", "#"), (r"\s+", ""), (r"△7|Δ7|M7|maj7|Maj7|ma7", "maj7"),
         (r"△|Δ", "maj7"), (r"\((sus4?|sus2|add\d+|\d+)\)", r"\1"), (r"sus(?!\d)", "sus4"),
         (r"[′'’]", "")]


def norm(t: str) -> str:
    """표기만 다른 코드를 같게 본다(maj7/M7/△7, E7(sus4)/E7sus4, sus/sus4, ♭/b)."""
    t = t or ""
    for a, b in _SAME:
        t = re.sub(a, b, t)
    return t


def compare(extraction: dict, reads: list[SystemChords]) -> list[tuple[int, list, list]]:
    """단별로 (단 번호, 첫 판독, 두 번째 판독) — 다른 단만."""
    ours = {s.get("index", i): [norm(c["text"]) for c in s.get("chords") or [] if not c.get("dropped")]
            for i, s in enumerate(extraction.get("systems") or [])}
    theirs = {r.system - 1: [norm(c) for c in r.chords if c.strip()] for r in reads}
    bad = []
    for k in sorted(set(ours) | set(theirs)):
        a, b = ours.get(k, []), theirs.get(k)
        if b is None:
            continue                     # 두 번째 판독이 그 단을 안 냈다 — 비교할 수 없다
        if a != b:
            bad.append((k, a, b))
    return bad


def check(img, extraction: dict) -> dict:
    """두 번째 판독을 하고, 다른 단에 확인 필요를 단다. 통계를 돌려준다."""
    geo = (extraction.get("geometry") or {}).get("systems") or []
    st = (extraction.get("struct") or {}).get("systems") or []
    if not geo or not st:
        return {"skipped": True}
    strip, idx = strip_image(img, geo)
    reads = read(strip, len(idx))
    bad = compare(extraction, reads)
    for k, a, b in bad:
        sys_ = next((s for s in st if s.get("system", -1) == k), None)
        if sys_ is not None and REVIEW not in sys_.setdefault("review", []):
            sys_["review"].append(REVIEW)
    return {"systems": len(idx), "diff": len(bad),
            "where": [f"{k}: {a} / {b}" for k, a, b in bad]}
