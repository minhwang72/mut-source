"""
**코드를 한 번 더 읽어 맞을 때만 믿는다** — 음표의 homr 교차 검증과 같은 생각.

첫 판독(read_chords)은 검출기가 자른 조각을 하나씩 읽는다. 그래서 검출기가
놓친 코드(손글씨·회색 상자)는 아예 없고, 조각에 가사 글자가 섞이면 'Asus2'
처럼 엉뚱한 코드가 된다. 과금 장 26장 대조에서 13장이 이걸로 틀렸다(2026-10-31).

두 번째 판독은 **단마다 오선 위 띠를 통째로** 보여 주고 왼쪽부터 순서대로,
몇 번째 마디인지와 함께 적게 한다. 단별로 둘을 견준다:
  같다                       → 그대로
  두 판독이 함께 읽은 코드의 마디 번호가 전부 맞는다
    · 글자만 다른 코드       → 두 번째를 쓴다(조각에 섞인 가사·작은 글자 오독)
    · 첫 판독이 놓친 코드     → 그 마디 코드 띠에서 아직 안 쓴 잉크 덩어리가
                               꼭 그 개수만큼 있을 때만, 그 자리에 넣는다
  그 밖(첫 판독에만 있는 코드, 마디가 어긋남, 자리를 못 찾음) → 확인 필요
두 번째 판독이 대조한 표본(약 60개)에서 전부 맞았다 — 그래도 혼자 읽은 코드는
마디 번호 일치와 잉크 자리로 한 번 더 묶는다. 덧칠해 지운 코드를 읽어 넣은 적이
있다(day2conti-4 단2 'G7') — 프롬프트에서 뺀다.
"""
from __future__ import annotations

import difflib
import re
import sys

from pydantic import BaseModel, Field

MODEL = "claude-sonnet-5-5"
REVIEW = "코드가 두 판독에서 다릅니다 — 원본 확인 필요"


class ChordAt(BaseModel):
    text: str = Field(description="코드 심볼")
    # 마디 번호는 받지만 쓰지 않는다(fix_system 주석) — 캐시를 살리려고 형식을 둔다
    measure: int = Field(description="그 단 안에서 몇 번째 마디인가(1부터)")


class SystemChords(BaseModel):
    system: int = Field(description="띠 왼쪽 빨간 번호")
    chords: list[ChordAt] = Field(description="그 띠의 코드, 왼쪽부터 순서대로")


class PageChords(BaseModel):
    systems: list[SystemChords]


PROMPT = """이 이미지는 악보의 단(오선 한 줄)마다 **오선 위쪽 띠**를 잘라 위에서부터 쌓은 것이다.
각 띠 왼쪽의 **빨간 숫자**가 단 번호다(코드가 아니다). 띠 아래쪽에 오선 윗부분과 마디선이 보인다.

띠 {n}개 전부에 대해, 그 단 위에 적힌 **코드 심볼을 왼쪽부터 순서대로** 적고, 각 코드가
그 단에서 **몇 번째 마디** 위에 있는지 적어라. 단 왼쪽 끝부터 첫 마디선까지가 1번 마디다
(음자리표·조표 구간 포함). 겹세로줄·도돌이 세로줄도 마디선으로 센다.

규칙:
- 보이는 대로 옮긴다. 올림표 `#`, 내림표 `b`. 예: Bb, Gm7, Ebmaj7, F#m7, Bb/D, Esus4, E7(sus4), D2/F#
- 분수코드 슬래시를 빠뜨리지 말 것(베이스음이 오른쪽 아래 작게 붙는다).
- 코드 둘이 붙어 있어도 따로 적는다(Esus4 E7 → 두 개).
- 손글씨·색깔 코드도 코드다. 괄호 안 대체 코드(예: `G/D(Em)`)는 괄호째 한 개로 적는다.
- **코드가 아닌 것은 빼라**: 가사, 연주 지시어(Fine, D.S., D.C., Coda, To Coda),
  구역 표시(A, B, C′ 같은 상자 글자), 템포, 마디 번호, 반복 괄호 번호(1., 2.).
- **줄을 긋거나 덧칠해 지운 코드는 빼라.** 연주자가 지운 것이다. 글자가 일부 보여도 적지 않는다.
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


def ink_runs(ink, x0: float, x1: float, y0: float, y1: float, sp: float) -> list[tuple]:
    """띠 안 잉크를 가로로 묶은 덩어리 (x 시작, x 끝). 0.8칸 넘게 비면 끊는다."""
    h, w = ink.shape
    a, b = max(0, int(x0)), min(w, int(x1))
    ys, ye = max(0, int(y0)), min(h, int(y1))
    if b <= a or ye <= ys:
        return []
    cols = ink[ys:ye, a:b].any(axis=0)
    out, start, gap = [], None, 0
    for i, v in enumerate(cols):
        if v:
            if start is None:
                start = i
            gap, last = 0, i
        elif start is not None:
            gap += 1
            if gap > sp * 0.8:
                out.append((a + start, a + last + 1))
                start = None
    if start is not None:
        out.append((a + start, a + last + 1))
    return [r for r in out if r[1] - r[0] >= sp * 0.5]


def _root(t: str) -> str:
    m = re.match(r"\(?([A-G][#b]?)", t or "")
    return m.group(1) if m else (t or "")


def fix_system(ours: list[dict], theirs: list[ChordAt], geo: dict, ink) -> list[dict] | None:
    """
    두 판독을 맞춘 코드 목록. 못 맞추면 None(확인 필요).

    **마디 번호는 쓰지 않는다** — 두 번째 판독이 마디를 하나 더 세는 일이 잦았다
    (실측 wish0906-2 단6 · wish0823-4 단4: 4마디 단에 5번 마디). 대신 두 판독이
    함께 읽은 코드를 기준점으로, 놓친 코드는 양옆 기준점 사이 코드 띠에서 아직
    안 쓴 잉크 덩어리가 꼭 그 개수만큼 있을 때만 그 자리에 넣는다. 글자가 다른
    코드는 근음이 같을 때만 짝지어 두 번째를 쓴다(가사가 섞인 'Asus2' → A).
    """
    sp = float(geo.get("spacing") or 10)
    a = [norm(c["text"]) for c in ours]
    b = [norm(c.text) for c in theirs]
    out = [dict(c) for c in ours]
    anchor: dict[int, int] = {}                       # 두 번째 판독 번호 → 첫 판독 번호
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            pairs = list(zip(range(i1, i2), range(j1, j2)))
        else:
            pairs, j = [], j1
            for i in range(i1, i2):
                while j < j2 and _root(b[j]) != _root(a[i]):
                    j += 1
                if j >= j2:
                    return None                       # 첫 판독에만 있는 코드 — 못 가른다
                pairs.append((i, j))
                j += 1
        for i, j in pairs:
            anchor[j] = i
            if a[i] != b[j]:
                out[i] = {**out[i], "text": theirs[j].text, "confidence": 0.6, "recheck": "text"}
    missing = [j for j in range(len(theirs)) if j not in anchor]
    if not missing:
        return sorted(out, key=lambda c: c["box"]["x"])
    # 코드 띠 높이: 이 단의 첫 판독 코드가 있던 높이, 없으면 오선 위 0.8~4칸
    top = float(geo["staffTop"])
    ys = [c["box"]["y"] for c in ours] + [c["box"]["y"] + c["box"]["h"] for c in ours]
    y0, y1 = (min(ys) - sp * 0.3, max(ys) + sp * 0.3) if ours else (top - sp * 4, top - sp * 0.8)
    y1 = min(y1, top - sp * 0.3)
    taken = [(c["box"]["x"], c["box"]["x"] + c["box"]["w"]) for c in ours]
    left, right = float(geo.get("left", 0)), float(geo.get("right", ink.shape[1]))
    k = 0
    while k < len(missing):
        grp = [missing[k]]
        while k + 1 < len(missing) and missing[k + 1] == grp[-1] + 1:
            k += 1
            grp.append(missing[k])
        k += 1
        prv, nxt = grp[0] - 1, grp[-1] + 1
        x0 = (ours[anchor[prv]]["box"]["x"] + ours[anchor[prv]]["box"]["w"]) if prv in anchor else left
        x1 = ours[anchor[nxt]]["box"]["x"] if nxt in anchor else right
        runs = [r for r in ink_runs(ink, x0 + sp * 0.2, x1 - sp * 0.2, y0, y1, sp)
                if not any(r[0] < t1 and t0 < r[1] for t0, t1 in taken)]
        if len(runs) != len(grp):
            return None                               # 자리를 못 찾으면 넣지 않는다
        for j, (r0, r1) in zip(grp, runs):
            out.append({"text": theirs[j].text, "box": {"x": r0, "y": y0, "w": r1 - r0, "h": y1 - y0},
                        "confidence": 0.6, "recheck": "added"})
    return sorted(out, key=lambda c: c["box"]["x"])


def check(img, extraction: dict, ink=None) -> dict:
    """두 번째 판독으로 코드를 맞추고, 못 맞춘 단에 확인 필요를 단다. 통계를 돌려준다."""
    geo = (extraction.get("geometry") or {}).get("systems") or []
    st = (extraction.get("struct") or {}).get("systems") or []
    if not geo or not st:
        return {"skipped": True}
    strip, idx = strip_image(img, geo)
    reads = {r.system - 1: r.chords for r in read(strip, len(idx))}
    systems = extraction.setdefault("systems", [])
    by = {s.get("index", i): s for i, s in enumerate(systems)}
    stat = {"systems": len(idx), "fixed": 0, "diff": 0, "where": []}
    for k in idx:
        if k not in reads:
            continue                     # 두 번째 판독이 그 단을 안 냈다 — 비교할 수 없다
        sysd = by.get(k)
        ours = [c for c in (sysd or {}).get("chords") or [] if not c.get("dropped")]
        theirs = [c for c in reads[k] if c.text.strip()]
        if [norm(c["text"]) for c in ours] == [norm(c.text) for c in theirs]:
            continue
        g = next((g for i, g in enumerate(geo) if g.get("index", i) == k), None)
        got = fix_system(ours, theirs, g, ink) if g is not None and ink is not None else None
        stat["where"].append(f"{k}: {[c['text'] for c in ours]} / "
                             f"{[(c.text, c.measure) for c in theirs]}"
                             + (" → 맞춤" if got is not None else ""))
        if got is not None:
            if sysd is None:
                sysd = {"index": k, "page": 0, "staffTop": g["staffTop"],
                        "staffBottom": g["staffBottom"], "chords": []}
                systems.append(sysd)
                systems.sort(key=lambda s: s.get("index", 0))
                by[k] = sysd
            dropped = [c for c in sysd.get("chords") or [] if c.get("dropped")]
            sysd["chords"] = sorted(got + dropped, key=lambda c: c["box"]["x"])
            stat["fixed"] += 1
            continue
        stat["diff"] += 1
        sys_ = next((s for s in st if s.get("system", -1) == k), None)
        if sys_ is not None and REVIEW not in sys_.setdefault("review", []):
            sys_["review"].append(REVIEW)
    return stat
