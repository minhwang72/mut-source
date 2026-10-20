#!/usr/bin/env python3
"""
단별 **음표 수·쉼표 수**만 LLM으로 읽는다. 구조 판독을 대체한다.

박자표도 여기서 받는다. 마디 합으로 3박인 것까지는 추정되지만 **6/8과 3/4는
합이 같아** 못 가른다 — 조판(빔 묶음)이 달라지므로 글자로 읽는 게 맞다.

왜 이것만 묻는가(실측): 음가·붙임점·마디는 검출기와 그림에서 나온다
(`detstruct` 첫머리 참고). 검출기에 남는 약점은 **점수가 낮은 기호**뿐이다 —
속 빈 머리(2분·온음표)는 0.03~0.58, 2분쉼표도 낮게 나와 하나의 문턱으로는
빠진다. 개수를 알면 그 수만큼만 낮은 점수를 받아 채울 수 있다
(`evaldet.detect_guided`).

출력이 단별 두 숫자뿐이라 사고 과정도 짧다 — 구조 판독의 출력 토큰이
비용의 82%였고 그 94%가 사고였다.

반복 기호(도돌이표·볼타)는 검출 클래스가 없으니 여기서 같이 받는다.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import readstruct as RS  # noqa: E402

PROMPT = """악보 한 단(system)입니다. **개수만** 세어 주세요. 음높이·음가는 묻지 않습니다.

1. **음표 머리 개수** — 이 단에 있는 음표의 개수
   · 빔(굵은 가로 막대)으로 묶인 음표는 각각 셉니다
   · **머리가 비어 있는 2분음표·온음표도 반드시 포함합니다** (놓치기 쉽습니다)
   · 붙임줄로 이어진 음표도 각각 셉니다
   · 회색으로 흐리게 인쇄된 선택 음표가 있으면 포함합니다

2. **쉼표 개수** — 이 단에 있는 쉼표의 개수
   · 온쉼표(줄에 매달린 작은 사각형)와 2분쉼표(줄 위에 앉은 사각형)를
     **둘 다 빠뜨리지 말고** 셉니다

3. **박자표** — 이 단 맨 앞에 박자표가 보이면 "4/4" 처럼 적고, 안 보이면
   빈 문자열로 두세요 (보통 첫 단에만 있습니다)

4. 반복 기호 (없으면 빈 목록)
   · **도돌이표 시작** 𝄆 — 굵은 줄 + 점 두 개가 마디 **왼쪽**
   · **도돌이표 끝** 𝄇 — 점 두 개 + 굵은 줄이 마디 **오른쪽**
   · **볼타**(1./2. 처럼 위에 상자로 씌운 구간) — 시작 마디 번호와 숫자"""


# **생각(thinking)은 max_tokens 안에서 쓰인다.** 2000으로 두면 생각이 긴
# 단에서 구조 출력이 나오기 전에 잘리고, 그러면 parsed_output 이 None 으로
# 와서 쪽 전체가 죽는다(실측: camp0814b-01 단5). 생각을 켤 때는 넉넉히 준다.
MAX_TOKENS = 2000
MAX_TOKENS_THINK = 8000


def read_system(img, model: str, think: bool = False) -> dict:
    from pydantic import BaseModel, Field
    import anthropic

    class Mark(BaseModel):
        measure: int = Field(description="몇 번째 마디인가 (1부터)")
        repeat_start: bool = Field(description="이 마디 왼쪽에 도돌이표 시작")
        repeat_end: bool = Field(description="이 마디 오른쪽에 도돌이표 끝")
        volta: str = Field(description="볼타 숫자. 없으면 빈 문자열")

    class Line(BaseModel):
        notes: int = Field(description="음표 머리 개수 (쉼표 제외)")
        rests: int = Field(description="쉼표 개수")
        time_signature: str = Field(
            description='이 단 맨 앞의 박자표 (예 "4/4", "6/8"). 없으면 빈 문자열')
        marks: list[Mark] = Field(description="반복 기호·볼타. 없으면 빈 목록")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.standard_b64encode(buf.getvalue()).decode()
    client = anthropic.Anthropic()

    def call(mt: int, thinking: bool):
        kw = {} if thinking else {"thinking": {"type": "disabled"}}
        return RS._with_retry(lambda: client.messages.parse(
            model=model, max_tokens=mt,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64",
                 "media_type": "image/png", "data": b64}},
                {"type": "text", "text": PROMPT}]}],
            output_format=Line, **kw))

    r = call(MAX_TOKENS_THINK if think else MAX_TOKENS, think)
    if r.parsed_output is None:
        # 잘렸다 — 생각을 끄고 한 번 더. 개수 세기는 생각 없이도 대체로 맞고,
        # 여기서 실패하면 그 단은 안내 없이 가야 하므로 훨씬 나쁘다.
        print(f"    구조 출력 없음({getattr(r, 'stop_reason', '?')}) — "
              "생각 끄고 재시도", file=sys.stderr)
        r = call(MAX_TOKENS, False)
    if r.parsed_output is None:
        raise ValueError(
            f"구조 출력을 받지 못했습니다 (stop_reason={getattr(r, 'stop_reason', '?')})")
    out = r.parsed_output.model_dump()
    out["_in"] = r.usage.input_tokens
    out["_out"] = r.usage.output_tokens
    return out


# **개수 세기는 구조 판독만큼 확대할 필요가 없다.** 구조 판독은 음가를
# 읽어야 해서 오선 간격 39px가 필요했다(readstruct.TARGET_SPACING). 개수는
# 머리를 알아보기만 하면 되고, 입력 토큰이 이제 비용의 절반이라 여기를
# 줄이는 게 그대로 절감이다.
TARGET_SPACING = 22.0


def read_page(img, model: str = "claude-opus-5", zoom: float | None = None,
              think: bool = False, target: float = TARGET_SPACING) -> dict:
    """쪽 전체를 단별로 세어 counts 를 만든다."""
    import sheetcv as cv
    from PIL import Image

    if zoom is None:
        _i, st0 = cv.find_staves_best(img.convert("L"))
        if not st0:
            raise ValueError("오선을 찾지 못했습니다.")
        sp0 = cv.median_spacing(st0)
        zoom = min(max(1.0, target / sp0) if sp0 > 0 else 1.0,
                   RS.MAX_SIDE / max(img.width, img.height))
    big = img.convert("RGB").resize(
        (int(img.width * zoom), int(img.height * zoom)), Image.LANCZOS)
    _ink, staves = cv.find_staves_best(big)
    if not staves:
        raise ValueError("오선을 찾지 못했습니다.")
    sp = cv.median_spacing(staves)

    systems, tin, tout = [], 0, 0
    for i, st in enumerate(staves):
        try:
            r = read_system(RS.crop_system(big, st, sp), model, think)
        except Exception as e:                              # noqa: BLE001
            # **한 단이 실패해도 쪽 전체를 버리지 않는다.** 개수 0은
            # detect_guided 에서 "안내 없음"과 같은 뜻이라, 그 단만 높은
            # 문턱 검출로 떨어진다(고신뢰 검출은 기대 개수와 무관하게
            # 남는다). 쪽을 통째로 잃는 것보다 한 단이 거친 게 낫다.
            print(f"  단{i}: 판독 실패 — 안내 없이 진행 ({e})", file=sys.stderr)
            r = {"notes": 0, "rests": 0, "time_signature": "",
                 "marks": [], "unread": True}
        tin += r.pop("_in", 0)
        tout += r.pop("_out", 0)
        r["system"] = i
        systems.append(r)
        print(f"  단{i}: 음표 {r['notes']}개 · 쉼표 {r['rests']}개",
              file=sys.stderr)
    return {"systems": systems, "tokens": {"in": tin, "out": tout}}


def main() -> None:
    ap = argparse.ArgumentParser(description="단별 음표·쉼표 개수만 판독")
    ap.add_argument("image")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--model", default="claude-opus-5")
    ap.add_argument("--target", type=float, default=TARGET_SPACING,
                    help="목표 오선 간격(px). 작을수록 입력 토큰이 줄어든다")
    ap.add_argument("--think", action="store_true",
                    help="사고를 켠다 (개수 세기에는 보통 불필요)")
    a = ap.parse_args()

    from PIL import Image
    res = read_page(Image.open(a.image), a.model, think=a.think,
                    target=a.target)
    Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1),
                           encoding="utf-8")
    t = res["tokens"]
    print(f"토큰 in {t['in']:,} / out {t['out']:,}", file=sys.stderr)
    print(a.out)


if __name__ == "__main__":
    main()
