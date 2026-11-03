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
  그래도 못 맞추면 align — 두 번째 판독을 주로, 자리는 띠 잉크 조각으로(2026-11-03)
  그 밖(첫 판독에만 있는 코드, 마디가 어긋남, 자리를 못 찾음) → 확인 필요
두 번째 판독이 대조한 표본(약 60개)에서 전부 맞았다 — 그래도 혼자 읽은 코드는
마디 번호 일치와 잉크 자리로 한 번 더 묶는다. 덧칠해 지운 코드를 읽어 넣은 적이
있다(day2conti-4 단2 'G7') — 프롬프트에서 뺀다.
"""
from __future__ import annotations

import difflib
import math
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
    if resp.parsed_output is None:              # 실측 t046-3: 형식 밖 응답
        raise RuntimeError(f"코드 재판독 응답을 읽지 못했습니다({resp.stop_reason})")
    u = resp.usage
    print(f"  코드 재판독 토큰 in {u.input_tokens} / out {u.output_tokens}", file=sys.stderr)
    return resp.parsed_output.systems


class CropChord(BaseModel):
    n: int = Field(description="빨간 번호")
    text: str = Field(description="그 칸의 코드 심볼, 코드가 아니거나 안 보이면 빈 문자열")


class CropChords(BaseModel):
    items: list[CropChord]


VOTE_PROMPT = """이 이미지는 악보에서 코드 심볼 하나씩을 잘라 위에서부터 쌓은 것이다.
각 줄 왼쪽 **빨간 숫자**는 번호다(코드가 아니다). 각 칸에 적힌 코드 심볼을 보이는 그대로 옮겨라.
올림표 `#`, 내림표 `b`. 분수코드 슬래시, 작은 숫자(7, 9, sus4, add2)를 빠뜨리거나 지어내지 말 것.
칸 가장자리에 걸친 옆 코드의 조각은 무시한다. 코드가 아니거나 안 보이면 빈 문자열.
{n}개 모두 번호와 함께 반환하라."""


def vote_image(img, boxes: list[dict]):
    """코드 상자마다 넉넉히 잘라 번호를 붙여 쌓는다."""
    from PIL import Image, ImageDraw
    import read_chords as RC
    crops = []
    for b in boxes:
        h = b["h"]
        c = img.crop((int(max(0, b["x"] - h * 0.4)), int(max(0, b["y"] - h * 0.35)),
                      int(min(img.width, b["x"] + b["w"] + h * 0.6)),
                      int(min(img.height, b["y"] + h * 1.35)))).convert("RGB")
        k = 90 / max(1, c.height)
        crops.append(c.resize((max(1, int(c.width * k)), 90)))
    pad = 60
    W = max(c.width for c in crops) + pad
    out = Image.new("RGB", (W, sum(c.height + 10 for c in crops)), "white")
    d = ImageDraw.Draw(out)
    font = RC.label_font(32)
    y = 0
    for i, c in enumerate(crops):
        out.paste(c, (pad, y))
        d.text((6, y + 25), str(i + 1), fill=(220, 0, 0), font=font)
        y += c.height + 10
    return out


def vote(im, n: int, model: str = MODEL) -> list[str]:
    """잘라 쌓은 코드를 하나씩 읽는다 — 띠 판독과 첫 판독이 갈린 코드의 세 번째 표."""
    import base64
    import io

    import anthropic
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    b64 = base64.standard_b64encode(buf.getvalue()).decode()
    resp = anthropic.Anthropic().messages.parse(
        model=model, max_tokens=4000,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
            {"type": "text", "text": VOTE_PROMPT.format(n=n)}]}],
        output_format=CropChords)
    if resp.parsed_output is None:
        raise RuntimeError(f"코드 표결 응답을 읽지 못했습니다({resp.stop_reason})")
    got = {it.n: it.text for it in resp.parsed_output.items}
    return [got.get(i + 1, "") for i in range(n)]


_SAME = [(r"[♭]", "b"), (r"[♯]", "#"), (r"\s+", ""), (r"△7|Δ7|M7|maj7|Maj7|ma7", "maj7"),
         (r"△|Δ", "maj7"), (r"\((sus4?|sus2|add\d+|\d+)\)", r"\1"), (r"sus(?!\d)", "sus4"),
         (r"[′'’]", "")]


def norm(t: str) -> str:
    """표기만 다른 코드를 같게 본다(maj7/M7/△7, E7(sus4)/E7sus4, sus/sus4, ♭/b)."""
    t = t or ""
    for a, b in _SAME:
        t = re.sub(a, b, t)
    return t


def ink_runs(ink, x0: float, x1: float, y0: float, y1: float, sp: float,
             gap: float = 0.8, minw: float = 0.5) -> list[tuple]:
    """띠 안 잉크를 가로로 묶은 덩어리 (x 시작, x 끝). gap 칸 넘게 비면 끊는다."""
    h, w = ink.shape
    a, b = max(0, int(x0)), min(w, int(x1))
    ys, ye = max(0, int(y0)), min(h, int(y1))
    if b <= a or ye <= ys:
        return []
    cols = ink[ys:ye, a:b].any(axis=0)
    out, start, blank = [], None, 0
    for i, v in enumerate(cols):
        if v:
            if start is None:
                start = i
            blank, last = 0, i
        elif start is not None:
            blank += 1
            if blank > sp * gap:
                out.append((a + start, a + last + 1))
                start = None
    if start is not None:
        out.append((a + start, a + last + 1))
    return [r for r in out if r[1] - r[0] >= sp * minw]


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
                out[i] = {**out[i], "text": theirs[j].text, "was": out[i]["text"],
                          "confidence": 0.6, "recheck": "text"}
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


def _letter(t: str) -> str:
    m = re.search(r"[A-G]", t or "")
    return m.group(0) if m else ""


def _len(t: str) -> int:
    return max(1, len(re.sub(r"[()\s]", "", t or "")))


def align(ours: list[dict], theirs: list[ChordAt], geo: dict, ink, band, cw=None,
          ch=None) -> list[dict] | None:
    """
    **두 번째 판독을 주로, 자리는 잉크로.** fix_system 이 못 맞춘 단을 다시 본다.

    실측(처음 보는 30장, 2026-11-03): 첫 판독은 한 글자 코드(E, A)·빨간 글씨를
    놓치고, `E♭/F` 를 'E'·'♭/F' 두 상자로 자르고, 'A/C# D' 를 한 상자로 묶었다.
    두 번째 판독은 7장 전부 맞았다. 그래서 코드 띠를 잘게 쪼갠 조각(첫 판독 상자
    + 상자 밖 잉크)을 x 순서로 놓고, 두 번째 판독 코드마다 **붙어 있는 조각 묶음**
    하나를 차례로 준다. 비용:
      묶음 폭이 글자 수로 본 폭과 다른 정도(로그 비), 묶음 안 빈틈(칸 단위)
      묶음 맨 앞 잉크가 코드 글자 같지 않으면(높이·바닥선이 이 장 코드와 다름) 0.8
      남는 잉크 조각을 버리는 값 — 코드 글자 같으면 1, 아니면(템포·%·괄호·점) 0.2
    첫 판독 상자는 버릴 수 없고, 묶음 맨 앞이면 근음 알파벳이 같아야 한다.
    가장 싼 짝짓기가 2등보다 0.5 이상 싸고 비용이 너무 크지 않을 때만 믿는다.
    """
    sp = float(geo.get("spacing") or 10)
    top = float(geo["staffTop"])
    if ours:
        ys = [c["box"]["y"] for c in ours] + [c["box"]["y"] + c["box"]["h"] for c in ours]
        y0, y1 = min(ys) - sp * 0.3, max(ys) + sp * 0.3
    elif band:
        y0, y1 = top - band[0] - sp * 0.3, top - band[1] + sp * 0.3
    else:
        return None
    y1 = min(y1, top - sp * 0.3)
    cw = cw or sp * 1.1                                          # 글자 하나 폭
    x0 = float(geo.get("headEnd") or geo.get("left") or 0) - sp * 0.5
    x1 = float(geo.get("right", ink.shape[1]))
    # 글자 수보다 1.6배 넘게 넓은 상자는 코드 둘(또는 상자 테두리)을 품은 것 — 잉크로 다시 쪼갠다
    boxes = [c for c in ours if c["box"]["w"] <= cw * _len(c["text"]) * 1.6]
    taken = [(c["box"]["x"], c["box"]["x"] + c["box"]["w"]) for c in boxes]
    cand = [("box", t0, t1, c) for (t0, t1), c in zip(taken, boxes)]
    cand += [("run", r0, r1, None) for r0, r1 in ink_runs(ink, x0, x1, y0, y1, sp, gap=0.35, minw=0.15)
             if not any(r0 < t1 and t0 < r1 for t0, t1 in taken)]
    cand.sort(key=lambda c: c[1])
    n, m = len(cand), len(theirs)
    INF = float("inf")
    # 코드 글자 같은가: 글자 높이(ch, 이 장 코드 상자 중앙값)와 바닥선(band[1])이 맞는 잉크
    ch = ch or sp * 1.2
    base = top - band[1] if band else y1
    like = []
    for kind, r0, r1, _ in cand:
        if kind == "box":
            like.append(True)
            continue
        rows = ink[int(y0):int(y1), int(r0):int(r1)].any(axis=1).nonzero()[0]
        h = rows[-1] - rows[0] + 1 if len(rows) else 0
        like.append(h > 0 and abs(math.log(h / ch)) < 0.4 and abs(y0 + rows[-1] - base) < ch * 0.45)

    def drop(i):
        return INF if cand[i][0] == "box" else (1.0 if like[i] else 0.2)

    def group(i, e, j):                       # 조각 i..e-1 을 코드 j 로
        if cand[i][0] == "box" and _letter(cand[i][3]["text"]) != _letter(theirs[j].text):
            return INF
        gaps = sum(max(0.0, cand[k][1] - cand[k - 1][2] - sp * 0.5) for k in range(i + 1, e))
        w = cand[e - 1][2] - cand[i][1]
        return (min(2.0, abs(math.log(max(w, 1) / (cw * _len(theirs[j].text)))))
                + gaps / sp + (0 if like[i] else 0.8))

    def solve(forbid=None):
        """가장 싼 짝짓기 (비용, [(코드 j, 조각 i, 끝 e)]). forbid=(j, k): 코드 j 가 조각 k 를 못 쓴다."""
        best = [[(INF, None)] * (m + 1) for _ in range(n + 1)]
        best[n][m] = (0.0, None)
        for i in range(n - 1, -1, -1):
            for j in range(m, -1, -1):
                o = (best[i + 1][j][0] + drop(i), ("drop",))
                if j < m:
                    for e in range(i + 1, n + 1):
                        if e > i + 1 and cand[e - 1][1] - cand[e - 2][2] > sp:
                            break                                # 1칸 넘게 떨어지면 한 코드가 아니다
                        if forbid and forbid[0] == j and i <= forbid[1] < e:
                            continue
                        c = group(i, e, j) + best[e][j + 1][0]
                        if c < o[0]:
                            o = (c, ("take", e))
                best[i][j] = o
        path, i, j = [], 0, 0
        if best[0][0][0] == INF:
            return INF, path
        while i < n:
            act = best[i][j][1]
            if act[0] == "drop":
                i += 1
                continue
            path.append((j, i, act[1]))
            i, j = act[1], j + 1
        return best[0][0][0], path

    def main(i, e):                                              # 묶음에서 가장 넓은 조각
        return max(range(i, e), key=lambda k: cand[k][2] - cand[k][1])

    c1, path = solve()
    if c1 == INF:
        return None
    # 2등: 어느 코드든 자기 자리(가장 넓은 조각)를 잃는 가장 싼 짝짓기 — 점·괄호를
    # 어디 붙이느냐만 다른 경로는 같은 답이라 세지 않는다
    c2 = min((solve((j, main(i, e)))[0] for j, i, e in path), default=INF)
    if c1 > 1.0 + 0.35 * m or c2 - c1 < 0.5:
        return None
    out = []
    for j, i, e in path:
        xs0, xs1 = cand[i][1], cand[e - 1][2]
        head = cand[i][3]
        if head is not None:
            bx = head["box"]
            ya, yb = bx["y"], bx["y"] + bx["h"]
            if e > i + 1:                                     # 조각을 합쳤다 — 띠 높이로
                ya, yb = min(ya, y0), max(yb, y1)
            box = {"x": xs0, "y": ya, "w": xs1 - xs0, "h": yb - ya}
            same = norm(head["text"]) == norm(theirs[j].text)
            out.append({**head, "box": box} if same else
                       {**head, "box": box, "text": theirs[j].text, "was": head["text"],
                        "confidence": 0.6, "recheck": "text"})
        else:
            out.append({"text": theirs[j].text, "box": {"x": xs0, "y": y0, "w": xs1 - xs0, "h": y1 - y0},
                        "confidence": 0.6, "recheck": "added"})
    return out


def _review(st: list[dict], k: int) -> None:
    sys_ = next((s for s in st if s.get("system", -1) == k), None)
    if sys_ is not None and REVIEW not in sys_.setdefault("review", []):
        sys_["review"].append(REVIEW)


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
    # 첫 판독 상자가 없는 단의 코드 띠 높이 — 이 장 다른 단 코드의 오선 위 높이(중앙값)
    tops = {g.get("index", i): float(g["staffTop"]) for i, g in enumerate(geo)}
    d0, d1 = [], []
    for s in systems:
        for c in s.get("chords") or []:
            if not c.get("dropped") and s.get("index") in tops:
                d0.append(tops[s["index"]] - c["box"]["y"])
                d1.append(tops[s["index"]] - c["box"]["y"] - c["box"]["h"])
    band = (sorted(d0)[len(d0) // 2], sorted(d1)[len(d1) // 2]) if d0 else None
    ws = sorted(c["box"]["w"] / _len(c["text"]) for s in systems for c in s.get("chords") or []
                if not c.get("dropped"))
    cw = ws[len(ws) // 2] if ws else None
    hs = sorted(c["box"]["h"] for s in systems for c in s.get("chords") or [] if not c.get("dropped"))
    ch = hs[len(hs) // 2] if hs else None
    fixed: dict[int, list[dict]] = {}
    for k in idx:
        if k not in reads:
            continue                     # 두 번째 판독이 그 단을 안 냈다 — 비교할 수 없다
        sysd = by.get(k)
        ours = [c for c in (sysd or {}).get("chords") or [] if not c.get("dropped")]
        theirs = [c for c in reads[k] if c.text.strip()]
        if [norm(c["text"]) for c in ours] == [norm(c.text) for c in theirs]:
            continue
        g = next((g for i, g in enumerate(geo) if g.get("index", i) == k), None)
        got = None
        if g is not None and ink is not None:
            got = fix_system(ours, theirs, g, ink) or align(ours, theirs, g, ink, band, cw, ch)
        stat["where"].append(f"{k}: {[c['text'] for c in ours]} / "
                             f"{[(c.text, c.measure) for c in theirs]}"
                             + (" → 맞춤" if got is not None else ""))
        if got is not None:
            fixed[k] = got
        else:
            _review(st, k)
            stat["diff"] += 1
    # **세 번째 표.** 두 판독의 글자가 다른 코드와 띠 판독만 읽은 코드는 그 자리만
    # 잘라 한 번 더 읽는다. 실측 t010-8 단1: 첫 판독 'E' 가 맞았는데 띠 판독이 윗단
    # 같은 자리의 'E7' 을 따라 읽어 그쪽으로 고쳤다. 띠와 같으면 띠, 첫 판독과 같으면
    # 첫 판독, 둘 다 아니면 확인 필요.
    todo = [(k, c) for k, got in fixed.items() for c in got if c.get("recheck")]
    if todo:
        third = vote(vote_image(img, [c["box"] for _, c in todo]), len(todo))
        stat["vote"] = []
        for (k, c), t in zip(todo, third):
            stat["vote"].append(f"{k}: {c.get('was')} / {c['text']} / {t}")
            if norm(t) == norm(c["text"]):
                continue
            if c.get("was") and norm(t) == norm(c["was"]):
                c["text"] = c.pop("was")
                c.pop("recheck", None)
                continue
            fixed[k] = None
    for k, got in fixed.items():
        if got is None:
            _review(st, k)
            stat["diff"] += 1
            continue
        g = next((g for i, g in enumerate(geo) if g.get("index", i) == k), None)
        sysd = by.get(k)
        if sysd is None:
            sysd = {"index": k, "page": 0, "staffTop": g["staffTop"],
                    "staffBottom": g["staffBottom"], "chords": []}
            systems.append(sysd)
            systems.sort(key=lambda s: s.get("index", 0))
            by[k] = sysd
        dropped = [c for c in sysd.get("chords") or [] if c.get("dropped")]
        sysd["chords"] = sorted([{x: v for x, v in c.items() if x != "was"} for c in got] + dropped,
                                key=lambda c: c["box"]["x"])
        stat["fixed"] += 1
    return stat
