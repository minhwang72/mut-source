#!/usr/bin/env python3
"""
단별 **음가·점·이음줄·마디 수**를 LLM으로 읽어 캐시한다.

역할 분담의 근거(실측): 음높이는 LLM이 82%(Opus 5, 6배 확대)로 못 믿지만
음가·이음줄·마디 수는 100%였다. 반대로 음높이는 검출기 좌표에서 뺄셈으로
정확히 나온다. 그래서 **읽는 것을 나눈다.**

가사는 묻지 않는다 — 한글 가사를 그럴듯하게 지어낸다(실측: "주 이름 찬양"을
"즐거운 찬란한"으로). 원본 픽셀 조각을 쓴다.

결과는 `<악보>.struct.json` 에 남긴다. 곡당 한 번만 호출한다.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

PROMPT = """악보 한 단(system)입니다. **음높이는 묻지 않습니다.** 아래만 읽어주세요.

- 이 단의 마디 수
- **음표와 쉼표를 왼쪽에서 오른쪽 순서로 모두** 세기
- 각 항목이 **몇 번째 마디**에 있는지 (1부터)
- 각 항목의 음가: whole / half / quarter / eighth / 16th
- 쉼표인지 음표인지
- 점음표인지
- (음표만) 다음 음표와 붙임줄(tie)로 이어지는지

주의:
- 빔(굵은 가로 막대)으로 묶인 음표는 각각 셉니다. 빔이 두 겹이면 16분음표입니다.
- 머리가 비어 있는 2분·온음표도 포함합니다.
- **한 마디의 음가 합은 박자표와 정확히 맞아야 합니다.** 4/4박이면 각 마디가
  4분음표 4개분입니다. 쉼표까지 넣어 세고, 합이 안 맞으면 다시 보세요.

반복 기호도 읽어주세요 (없으면 빈 목록):
- **도돌이표 시작** 𝄆 — 굵은 줄 + 점 두 개가 마디 **왼쪽**에 있는 마디 번호
- **도돌이표 끝** 𝄇 — 점 두 개 + 굵은 줄이 마디 **오른쪽**에 있는 마디 번호
- **볼타**(1./2. 처럼 위에 상자로 씌운 구간) — 시작 마디 번호와 숫자
  (예: 마디 3에서 "1.", 마디 4에서 "2.")"""


# 실측: 원본(오선 간격 6.5px)을 6배로 키운 게 판독 정확도 최적이었다.
# 그래서 배수가 아니라 **목표 오선 간격**으로 기억한다 — 이미 확대된 이미지를
# 또 6배 하면 폭이 9,900px이 되어 API 상한(8,000px)에 걸린다(실측: 서버에서
# 구조 판독이 400으로 실패했다).
TARGET_SPACING = 39.0
MAX_SIDE = 7800     # API 상한 8,000px보다 여유 있게


def crop_system(big, st, sp: float) -> "Image":
    """단 하나를 잘라 낸다. 위·아래로 코드와 가사가 들어올 만큼 여유를 준다."""
    y0 = max(0, int(st.top - sp * 4.0))
    y1 = min(big.height, int(st.bottom + sp * 4.5))
    x0 = max(0, int(st.left - sp * 2))
    x1 = min(big.width, int(st.right) + int(sp * 2))
    return big.crop((x0, y0, x1, y1))


def zoom_for(img, spacing: float) -> float:
    """
    판독용 확대 배율. **목표 오선 간격에 맞춘다.**

    들어오는 이미지가 이미 확대돼 있을 수 있으므로(서버는 렌더 품질을 위해
    미리 키운다) 고정 배수를 쓰면 안 된다. 긴 변이 API 상한을 넘지 않도록도
    잡는다.
    """
    z = TARGET_SPACING / spacing if spacing > 0 else 1.0
    z = max(1.0, z)
    return min(z, MAX_SIDE / max(img.width, img.height))


def read_page(img, model: str = "claude-opus-5",
              zoom: float | None = None, retry_rounds: int = 2,
              think: bool = False) -> dict:
    """
    쪽 전체를 단별로 판독한다. 서버와 CLI가 같은 경로를 쓰게 하려고 뺐다.
    zoom을 주지 않으면 오선 간격을 재서 스스로 정한다.

    반환: {"systems": [{"system": i, "measures": n, "notes": [...]}, ...],
           "tokens": {...}}
    """
    import sheetcv as cv
    from PIL import Image

    if zoom is None:
        _i0, st0 = cv.find_staves_best(img.convert("L"))
        if not st0:
            raise ValueError("오선을 찾지 못했습니다.")
        zoom = zoom_for(img, cv.median_spacing(st0))
    big = img.convert("RGB").resize(
        (int(img.width * zoom), int(img.height * zoom)), Image.LANCZOS)
    _ink, staves = cv.find_staves_best(big)
    if not staves:
        raise ValueError("오선을 찾지 못했습니다.")
    sp = cv.median_spacing(staves)
    print(f"  판독 확대 {zoom:.2f}배 → {big.width}×{big.height}, "
          f"오선 간격 {sp:.1f}px", file=sys.stderr)

    # **단끼리 독립이므로 동시에 부른다.** 순차로 하면 단 9개에 2분이 넘어
    # 웹에서 못 쓴다(실측: 요청이 2분 타임아웃에 걸렸다). 동시에 부르면
    # 가장 느린 한 단만큼만 걸린다.
    from concurrent.futures import ThreadPoolExecutor

    crops = [crop_system(big, st, sp) for st in staves]

    def one(c):
        """한 단이 실패해도 쪽 전체를 버리지 않는다 — 그 단만 비운다."""
        try:
            return read_system(c, model, think)
        except Exception as e:                       # noqa: BLE001
            return {"error": str(e)}

    # 동시 4개까지. 9개를 한꺼번에 부르면 과부하(529)가 실제로 걸렸다.
    with ThreadPoolExecutor(max_workers=min(4, len(crops))) as pool:
        outs = list(pool.map(one, crops))

    res, tin, tout, failed = [], 0, 0, []
    for i, r in enumerate(outs):
        if "error" in r:
            failed.append(i)
            res.append({"system": i, "measures": 0, "notes": [],
                        "error": r["error"]})
            print(f"  단{i}: 판독 실패 — {r['error'][:90]}", file=sys.stderr)
            continue
        tin += r["tokens"]["in"]
        tout += r["tokens"]["out"]
        res.append({"system": i, "measures": r["measures"],
                    "notes": r["notes"], "marks": r.get("marks") or []})
        print(f"  단{i}: {r['measures']}마디 · "
              f"음표·쉼표 {len(r['notes'])}개", file=sys.stderr)
    if failed:
        print(f"  ⚠️  {len(failed)}단 판독 실패 (단 {failed}) — 그 단은 비워 둡니다",
              file=sys.stderr)

    # **박자가 안 맞는 단만 다시 읽는다.**
    #
    # 정답 악보가 없어도 4/4박이면 마디마다 음가 합이 맞아야 한다. 그게 안 맞는
    # 단은 판독이 흐트러진 것이므로 다시 물으면 나아질 가능성이 있다 —
    # LLM은 같은 그림에도 매번 조금 다르게 답한다(실측: 같은 악보를 두 번
    # 읽었더니 박자 검산이 41/41과 37/42로 갈렸다. 반복 기호까지 함께 물은
    # 쪽이 나빴다 — 한 번에 많이 물으면 음표 읽기가 흐트러진다).
    #
    # 개선되지 않으면 원래 답을 둔다. 나빠지는 쪽으로 바꾸지 않는다.
    for _round in range(retry_rounds):
        bad = _bad_systems(res)
        if not bad:
            break
        print(f"  박자가 안 맞는 단 {bad} — 다시 읽습니다", file=sys.stderr)
        fixed = 0
        for i in bad:
            try:
                r = read_system(crops[i], model, think)
            except Exception as e:                   # noqa: BLE001
                print(f"    단{i} 재판독 실패: {str(e)[:70]}", file=sys.stderr)
                continue
            tin += r["tokens"]["in"]
            tout += r["tokens"]["out"]
            cand = {"system": i, "measures": r["measures"],
                    "notes": r["notes"], "marks": r.get("marks") or []}
            # 후보를 끼워 넣고 전체로 다시 재야 쪼개진 마디 판정이 맞다
            before = _bad_by_system(res).get(i, 0)
            trial = list(res)
            trial[i] = cand
            after = _bad_by_system(trial).get(i, 0)
            if after < before:
                res[i] = cand
                fixed += 1
                print(f"    단{i}: 어긋난 마디 {before} → {after}",
                      file=sys.stderr)
            else:
                print(f"    단{i}: 나아지지 않아 그대로 둡니다 "
                      f"({before} → {after})", file=sys.stderr)
        if not fixed:
            break

    return {"systems": res, "tokens": {"in": tin, "out": tout},
            "failed": failed}


def _bad_by_system(res: list[dict], beats: int = 4) -> dict[int, int]:
    """
    단마다 박자가 어긋난 마디 수. **checkbeats와 같은 판정을 쓴다.**

    처음엔 여기서 따로 셌는데, 첫·마지막 마디의 미달을 "쪼개진 마디일 수
    있다"며 눈감아 주다가 **진짜 오류를 덮었다**(실측: 젊은이교회 단1 마디1의
    2박 미달을 놓쳤다). checkbeats는 앞뒤 단을 짝지어 쪼개진 마디를 정확히
    가려내므로 그것을 쓴다.
    """
    import checkbeats as CB

    r = CB.check({"systems": res}, beats)
    out: dict[int, int] = {}
    for i, sysd in enumerate(res):
        if not sysd.get("notes"):
            out[i] = 99                    # 아예 못 읽은 단
    for i, _m, _v in r["over"] + r["under"]:
        out[i] = out.get(i, 0) + 1
    return out


def _bad_systems(res: list[dict]) -> list[int]:
    """다시 읽을 단 번호."""
    return sorted(i for i, n in _bad_by_system(res).items()
                  if n > 0 and res[i].get("notes"))


# 재시도. 단 9개를 동시에 부르면 과부하(529)·속도제한(429)이 실제로 걸린다
# (실측: 서버에서 구조 판독이 529로 통째로 실패했다). 지수 대기로 다시 부른다.
# **확장 사고를 끈다.** Opus 5는 기본으로 사고 과정을 쓰는데, 그게 출력 토큰의
# 94%를 차지한다(실측: 답이 389토큰인데 출력이 6,105토큰). 이 일은 그림을 보고
# 세는 것이라 긴 사고가 필요 없다 — 껐더니 출력이 7.2배 줄고 결과는 같았다.
# 악보 한 장 변환 비용이 $2.8 → $0.4 수준이 된다.
# 사고를 켤지 끌지. Opus 5는 한도를 못 주므로 True/False뿐이다.
# **끄면 마디 수가 틀린다**(실측: 마커스 9단 중 4단에서 마디 수 오류) —
# 기본은 켠다. 비용을 줄이려면 모델을 낮추는 쪽으로 간다.
THINK_BUDGET = True

RETRIES = 4
BACKOFF = 3.0
# 출력 토큰 예산. 실측: 8,000이면 음표·쉼표 25개 넘는 단에서 JSON이 잘리고,
# 24,000부터는 SDK가 비스트리밍을 거부한다("Streaming is required").
MAX_TOKENS_LO = 8000
MAX_TOKENS_HI = 20000


def _with_retry(fn):
    """429·529·연결 오류만 다시 시도한다. 400(잘못된 요청)은 재시도해도 같다."""
    import random
    import time

    last = None
    for i in range(RETRIES):
        try:
            return fn()
        except Exception as e:                       # noqa: BLE001
            msg = str(e)
            retryable = ("429" in msg or "529" in msg or "overloaded" in msg
                         or "rate_limit" in msg or "Connection" in msg
                         or "timeout" in msg.lower())
            if not retryable or i == RETRIES - 1:
                raise
            last = e
            wait = BACKOFF * (2 ** i) + random.uniform(0, 1.5)
            print(f"    다시 시도 {i+1}/{RETRIES-1} — {wait:.1f}초 뒤 "
                  f"({msg[:60]})", file=sys.stderr)
            time.sleep(wait)
    raise last


def read_system(img, model: str, think=THINK_BUDGET) -> dict:
    from pydantic import BaseModel, Field
    import anthropic

    class Note(BaseModel):
        order: int = Field(description="왼쪽부터 몇 번째인가 (쉼표 포함, 1부터)")
        measure: int = Field(description="몇 번째 마디인가 (1부터)")
        duration: str = Field(description="whole/half/quarter/eighth/16th")
        is_rest: bool = Field(description="쉼표인가 (음표가 아니면 True)")
        dotted: bool = Field(description="점음표인가")
        tied_to_next: bool = Field(description="다음 음표와 붙임줄로 이어지는가")

    class Mark(BaseModel):
        measure: int = Field(description="몇 번째 마디인가 (1부터)")
        repeat_start: bool = Field(description="이 마디 왼쪽에 도돌이표 시작")
        repeat_end: bool = Field(description="이 마디 오른쪽에 도돌이표 끝")
        volta: str = Field(description="볼타 숫자. 없으면 빈 문자열 (예: '1.')")

    class Line(BaseModel):
        measures: int = Field(description="이 단의 마디 수")
        notes: list[Note]
        marks: list[Mark] = Field(
            description="반복 기호·볼타. 없으면 빈 목록")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.standard_b64encode(buf.getvalue()).decode()
    client = anthropic.Anthropic()

    def call(max_tokens: int):
        # **사고를 아예 끄면 마디 수가 틀린다.** 실측(마커스 9단):
        #   사고 켬(기본) 마디 [5,4,4,4,5,3,4,4,6] · 박자 37/38 · $2.84
        #   사고 끔       마디 [5,4,4,3,4,3,3,4,5] · 박자 31/35 · $1.88
        # 마디 수가 틀리면 배치가 무너지므로 끄면 안 된다. 대신 **한도**를 둔다 —
        # 세는 일에 긴 사고가 필요하진 않다.
        # **한도는 못 준다.** Opus 5는 `thinking.type.enabled`를 지원하지 않아
        # 켜거나 끄거나 둘 중 하나다(실측: budget 1024·2048·4096 전부 400).
        kw = {} if think else {"thinking": {"type": "disabled"}}
        return _with_retry(lambda: client.messages.parse(
            model=model, max_tokens=max_tokens,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64",
                 "media_type": "image/png", "data": b64}},
                {"type": "text", "text": PROMPT}]}],
            output_format=Line, **kw))

    # **응답이 잘리는 걸 삼키지 않는다.** 실측: 한 단에 음표·쉼표가 25개를
    # 넘으면 8,000토큰으로 부족해 JSON이 중간에서 끊겼다("Invalid JSON: EOF
    # while parsing at column 1962"). 그건 예외로 던져지므로 parsed_output이
    # None인지 보는 것만으로는 못 잡는다.
    #
    # 그리고 **한없이 올릴 수도 없다.** 실측: 20,000까지는 비스트리밍으로
    # 받지만 24,000부터 SDK가 "Streaming is required"로 거부한다
    # (직접 겪었다 — 9단이 전부 실패했다).
    for budget in (MAX_TOKENS_LO, MAX_TOKENS_HI):
        try:
            r = call(budget)
        except Exception as e:                       # noqa: BLE001
            msg = str(e)
            truncated = ("EOF while parsing" in msg or "json_invalid" in msg
                         or "Invalid JSON" in msg)
            if not truncated or budget == MAX_TOKENS_HI:
                raise
            print(f"    응답이 잘렸습니다({budget}토큰) — "
                  f"{MAX_TOKENS_HI}으로 다시 시도", file=sys.stderr)
            continue
        o = r.parsed_output
        if o is not None:
            break
        why = getattr(r, "stop_reason", "?")
        if why != "max_tokens" or budget == MAX_TOKENS_HI:
            raise ValueError(
                f"구조 판독 응답을 해석하지 못했습니다 (stop_reason={why}).")
        print(f"    응답이 잘렸습니다({budget}토큰) — "
              f"{MAX_TOKENS_HI}으로 다시 시도", file=sys.stderr)
    else:
        raise ValueError("구조 판독 응답을 해석하지 못했습니다.")
    return {"marks": [{"measure": mk.measure,
                       "repeatStart": mk.repeat_start,
                       "repeatEnd": mk.repeat_end,
                       "volta": (mk.volta or "").strip()}
                      for mk in (o.marks or [])
                      if mk.repeat_start or mk.repeat_end or mk.volta],
            "measures": o.measures,
            "notes": [{"measure": n.measure, "duration": n.duration,
                       "rest": n.is_rest, "dotted": n.dotted,
                       "tie": n.tied_to_next}
                      for n in o.notes],
            "tokens": {"in": r.usage.input_tokens, "out": r.usage.output_tokens}}


def main() -> None:
    ap = argparse.ArgumentParser(description="단별 구조 판독 (캐시)")
    ap.add_argument("image")
    ap.add_argument("-o", "--out")
    ap.add_argument("--model", default="claude-opus-5")
    ap.add_argument("--zoom", type=float, default=None,
                    help="확대 배율. 안 주면 오선 간격 %g px에 맞춘다"
                         % TARGET_SPACING)
    ap.add_argument("--think", default="on",
                    help="확장 사고. off로 끄면 싸지만 마디 수가 틀린다")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    from PIL import Image

    import sheetcv as cv

    src = Path(a.image)
    out = Path(a.out) if a.out else src.with_suffix(".struct.json")
    if out.exists() and not a.force:
        print(f"이미 있음 — 재사용: {out}", file=sys.stderr)
        print(out)
        return

    img = Image.open(src).convert("RGB")
    th = a.think != "off"
    data = read_page(img, a.model, a.zoom, think=th)
    res, tin, tout = data["systems"], data["tokens"]["in"], data["tokens"]["out"]

    out.write_text(json.dumps({"systems": res,
                               "tokens": {"in": tin, "out": tout}},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"토큰 in {tin:,} / out {tout:,}", file=sys.stderr)
    print(out)


if __name__ == "__main__":
    main()
