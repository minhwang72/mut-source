#!/usr/bin/env python3
"""
AI 코드 판독 — 검출된 박스를 잘라 한 장의 격자 이미지로 묶어 한 번에 읽는다.

왜 이런 방식인가:
  · 박스 위치는 이미 영상처리로 픽셀 단위로 잡혀 있다. AI에게 좌표를 물으면
    오히려 부정확하다. AI는 **글자만** 읽으면 된다.
  · 박스 43개를 43번 호출하면 비싸고 느리다. 한 장의 격자로 묶으면 **1번**이다.
  · 잘라낸 조각은 배경이 거의 없어 판독 정확도가 원본 전체보다 높다.
  · 작은 조각을 확대해 붙이므로 저해상도 원본에서도 읽힌다.

    python3 tools/read_chords.py <이미지> <detect.json> -o extraction.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 실측(마커스 "내 마음 다해", 코드 43개): Haiku 4.5 / Sonnet 5 / Opus 5 모두
# 정확도 100%. 조각을 130px로 확대해 붙이므로 판독이 쉬운 작업이라 모델 급이
# 결과를 가르지 않았다. 원가는 Haiku가 Opus의 1/6.6 (13원 vs 86원/장).
#
# ⚠️ 근거는 인쇄 악보 1장이다. 손글씨·저품질 악보로 재검증 전까지는
#    --model claude-opus-5 로 되돌릴 수 있게 유지한다.
MODEL = "claude-haiku-4-5"
# 라벨 글자는 LLM 이 읽는다 — 맥에만 있는 경로를 박아두면 리눅스 컨테이너에서
# 판독이 통째로 죽는다. 있는 걸 찾아 쓰고, 없으면 Pillow 기본 글꼴로 버틴다.
LABEL_FONTS = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
)


def label_font(size: int = 40):
    for path in LABEL_FONTS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size)

# 격자 한 줄에 넣을 조각 수. 너무 많으면 각 조각이 작아지고,
# 너무 적으면 이미지가 길어진다.
COLS = 6
# 조각의 목표 높이(px). 원본 박스가 16px이어도 이만큼 확대해서 붙인다.
TILE_H = 130
# 박스를 자를 때 둘레 여유 비율 — 글리프가 잘리지 않게
PAD_RATIO = 0.18


class ChordRead(BaseModel):
    """조각 하나의 판독 결과"""
    index: int = Field(description="조각의 번호 (이미지에 빨간 숫자로 표시됨)")
    is_chord: bool = Field(
        description="이 조각이 코드 심볼인가? 음표·기둥·빔·오선 부스러기·빈 칸이면 false. "
        "검출기가 코드가 아닌 것을 잘라 넣는 경우가 있으므로 반드시 판단해야 한다."
    )
    text: str = Field(
        description="읽은 코드 심볼을 ASCII로. 올림표는 #, 내림표는 b. "
        "예: Bb, Gm7, Ebmaj7, F#m7, Bb/D, D7+5, Fsus, F2. "
        "is_chord가 false면 빈 문자열."
    )
    confidence: float = Field(description="판독 확신도 0.0~1.0")


class ChordSheet(BaseModel):
    chords: list[ChordRead]


PROMPT = """이 이미지는 악보에서 잘라낸 **코드 심볼** 조각들을 격자로 모은 것이다.
각 조각 왼쪽의 **빨간 숫자**는 조각 번호이며, 코드의 일부가 아니다.

조각 {n}개 전부를 번호 순서대로 읽어라.

읽기 규칙:
- 근음(A~G) + 임시표 + 성질을 그대로 옮긴다. 해석하거나 정규화하지 말 것.
- 올림표는 `#`, 내림표는 `b`로 쓴다. (예: B♭ → `Bb`, F♯m7 → `F#m7`)
- 윗숫자·아래첨자는 이어붙인다. G 아래 m, 위 7 → `Gm7`. E 위 b, maj, 위 7 → `Ebmaj7`
- **분수코드의 슬래시를 빠뜨리지 말 것.** 악보에서는 슬래시가 아주 작고
  베이스음이 오른쪽 아래에 붙어 그려진다 (E♭ 오른쪽에 작게 `/F`). 그래도
  슬래시를 넣어 `Eb/F`로 쓴다. `Ebf`처럼 붙여 쓰면 다른 코드가 된다.
  근음 뒤에 성질(m·maj·sus·dim·7 …) 없이 **음이름 글자만** 오면 그건 거의
  항상 분수코드다.
- `sus`, `2`, `+5`, `add9` 같은 표기는 보이는 대로. (예: `Fsus`, `F2`, `D7+5`)
- **보이는 글자를 무조건 적어라.** 코드가 아닌 것 같아도 text에 보이는 대로 쓴다.
  코드 여부는 뒤에서 파서가 판정하므로, 판단이 애매하면 그냥 적고 confidence를 낮춘다.
- 검출기가 음표·기둥·빔·오선 조각을 잘라 넣기도 한다. 글자가 아예 없으면
  `is_chord: false`, text는 빈 문자열.
- 흐리거나 애매하면 추측해서 적고 confidence를 낮춘다. **단독 `F` 같은 한 글자
  코드도 정상적인 코드다** — 짧다고 코드가 아니라고 판단하지 말 것.

번호를 빠뜨리지 말고 {n}개를 모두 반환하라."""


def load_image(path: str) -> Image.Image:
    return ImageOps.exif_transpose(Image.open(path)).convert("RGB")


def flatten_boxes(detect: dict) -> list[dict]:
    """검출 JSON을 (단, x) 순서로 평탄화하고 원래 위치를 기억시킨다."""
    out = []
    for sysd in detect["systems"]:
        for c in sorted(sysd["chords"], key=lambda b: b["x"]):
            out.append({"system": sysd["index"], **c})
    return out


def build_collage(img: Image.Image, boxes: list[dict]) -> tuple[Image.Image, int]:
    """
    조각들을 번호가 붙은 격자 이미지로 만든다.
    번호는 조각 바깥 여백에 빨간색으로 — 악보는 검정이므로 혼동되지 않는다.
    """
    tiles: list[Image.Image] = []
    for b in boxes:
        pad_x = max(2, int(b["w"] * PAD_RATIO))
        pad_y = max(2, int(b["h"] * PAD_RATIO))
        crop = img.crop((
            max(0, b["x"] - pad_x), max(0, b["y"] - pad_y),
            min(img.width, b["x"] + b["w"] + pad_x),
            min(img.height, b["y"] + b["h"] + pad_y),
        ))
        scale = TILE_H / max(1, crop.height)
        tiles.append(crop.resize(
            (max(1, int(crop.width * scale)), TILE_H), Image.LANCZOS))

    label_w = 62
    gap = 14
    col_w = label_w + max(t.width for t in tiles) + gap
    rows = (len(tiles) + COLS - 1) // COLS
    row_h = TILE_H + gap

    canvas = Image.new("RGB", (col_w * COLS + gap, row_h * rows + gap), (245, 245, 245))
    d = ImageDraw.Draw(canvas)
    font = label_font(40)

    for i, t in enumerate(tiles):
        r, c = divmod(i, COLS)
        x = gap + c * col_w
        y = gap + r * row_h
        d.text((x, y + TILE_H // 2 - 24), str(i), fill=(220, 0, 0), font=font)
        tx = x + label_w
        # 조각 배경을 흰색으로 깔아 경계를 분명히 한다
        canvas.paste(Image.new("RGB", (t.width, TILE_H), (255, 255, 255)), (tx, y))
        canvas.paste(t, (tx, y))
        d.rectangle([tx - 1, y - 1, tx + t.width, y + TILE_H], outline=(170, 170, 170))

    return canvas, len(tiles)


def read(collage: Image.Image, n: int, model: str = MODEL) -> list[ChordRead]:
    import base64
    import io

    import anthropic

    buf = io.BytesIO()
    collage.save(buf, format="PNG")
    b64 = base64.standard_b64encode(buf.getvalue()).decode()

    client = anthropic.Anthropic()
    # adaptive thinking은 4.6 세대 이상에서만 된다. Haiku 4.5는 400을 낸다
    # ("adaptive thinking is not supported on this model").
    # 조각 판독은 추론이 거의 필요 없는 작업이라 thinking 없이도 정확도가 같다.
    kwargs = {}
    if not model.startswith("claude-haiku-4-5"):
        kwargs["thinking"] = {"type": "adaptive"}

    resp = client.messages.parse(
        model=model,
        max_tokens=16000,
        **kwargs,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image",
                 "source": {"type": "base64", "media_type": "image/png", "data": b64}},
                {"type": "text", "text": PROMPT.format(n=n)},
            ],
        }],
        output_format=ChordSheet,
    )
    if resp.stop_reason == "refusal":
        raise SystemExit(f"모델이 요청을 거절했습니다: {resp.stop_details}")
    usage = resp.usage
    print(f"  토큰 in {usage.input_tokens} / out {usage.output_tokens}", file=sys.stderr)
    return resp.parsed_output.chords


def validate_with_parser(texts: list[str]) -> list[bool]:
    """
    코드 여부를 TS 코어의 파서로 판정한다.

    AI에게 맡기면 틀린다 — 실측으로 Haiku가 단독 `F`를 "코드 아님"으로 거부해
    실제 코드 하나가 사라졌다. 파싱되면 코드다. 이 판정은 결정론적이다.
    """
    import subprocess

    proc = subprocess.run(
        ["node", "--disable-warning=ExperimentalWarning", "--experimental-strip-types",
         str(Path(__file__).resolve().parent.parent / "src" / "cli.ts"), "validate"],
        input=json.dumps({"chords": texts}), capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(f"파서 호출 실패:\n{proc.stderr}")
    return [r["isChord"] for r in json.loads(proc.stdout)["results"]]


# 분수코드의 슬래시를 빠뜨린 형태를 되살린다.
#
# 왜 필요한가(실측): 악보에서 슬래시는 아주 작고 베이스음이 오른쪽 아래에
# 붙어 그려진다. 판독이 그걸 놓치면 `Eb/F`가 `Ebf`가 되고, 파서는 그걸
# **통과시킨다** — 성질 표기를 "보이는 대로" 받는 설계라서 `f`도 성질로
# 본다. 그래서 "파서가 거부한 것만 고친다"로는 안 잡힌다.
#
# 판정: 근음(+임시표)을 떼고 남은 꼬리가 **음이름 한 글자(+임시표)** 이고
# 성질 표기가 아닐 때. `Bb`는 임시표가 근음에 먹히므로 꼬리가 비어 걸리지
# 않는다 — 이게 중요하다. 정규식만으로 하면 `Bb`가 `B/B`가 되어 내림표
# 코드 전부가 깨진다(직접 겪었다).
_TAIL_NOTE = re.compile(r"^[A-Ga-g][#b]?$")


def _split_root(sym: str) -> tuple[str, str]:
    """'Ebf' → ('Eb', 'f'). 근음 글자와 임시표만 떼어낸다."""
    i = 1
    while i < len(sym) and sym[i] in "#b\u266f\u266d":
        i += 1
    return sym[:i], sym[i:]


def repair_slash(text: str) -> str | None:
    """슬래시를 되살린 글자, 아니면 None."""
    if not text or "/" in text or not text[0].upper() in "ABCDEFG":
        return None
    root, tail = _split_root(text)
    if not _TAIL_NOTE.match(tail):
        return None
    return f"{root}/{tail[0].upper()}{tail[1:]}"


def to_extraction(detect: dict, boxes: list[dict], reads: list[ChordRead],
                  meta: dict) -> dict:
    by_index = {r.index: r for r in reads}
    texts = [(by_index[i].text.strip() if i in by_index else "")
             for i in range(len(boxes))]
    # 슬래시를 되살린다. 고친 것은 확신도를 깎아 **사용자 확인 목록에
    # 올린다** — 조용히 바꾸지 않는다.
    fixed = set()
    for i, t in enumerate(texts):
        r = repair_slash(t)
        if r:
            texts[i] = r
            fixed.add(i)
    if fixed:
        print(f"  슬래시를 되살린 코드: {len(fixed)}개 "
              f"({', '.join(sorted(texts[i] for i in fixed))})", file=sys.stderr)
    valid = validate_with_parser(texts)
    systems: dict[int, dict] = {}
    dropped = 0

    for i, b in enumerate(boxes):
        r = by_index.get(i)
        # 파서가 최종 판정한다. 모델의 is_chord는 신뢰도 힌트로만 쓴다.
        if r is None or not valid[i]:
            dropped += 1
            continue
        s = systems.setdefault(b["system"], {"index": b["system"], "page": 0,
                                            "chords": []})
        s["chords"].append({
            "text": texts[i],
            "box": {"x": b["x"], "y": b["y"], "w": b["w"], "h": b["h"]},
            # 모델이 "코드 아님"이라 했지만 파서가 통과시킨 경우는 확신도를 깎아
            # 사용자 확인 목록에 올린다.
            "confidence": round(float(r.confidence)
                               * (1.0 if r.is_chord else 0.6)
                               * (0.7 if i in fixed else 1.0), 2),
        })

    for sysd in detect["systems"]:
        if sysd["index"] in systems:
            systems[sysd["index"]]["staffTop"] = sysd["staffTop"]
            systems[sysd["index"]]["staffBottom"] = sysd["staffBottom"]

    print(f"  코드로 인식되지 않아 버린 조각: {dropped}개", file=sys.stderr)
    return {
        "meta": meta,
        "imageSize": detect["imageSize"],
        "systems": [systems[k] for k in sorted(systems)],
    }


def _guess_key(img, texts: list[str], model_path: str | None) -> str:
    """
    원조성을 추정한다. **조표를 세는 게 코드 통계보다 확실하다.**

    실측: 코드가 `Bb C F Gm F/A`인 악보를 코드만으로는 Bb키로 봤는데(확신도
    0.13) 실제는 F키였다 — 조표는 ♭ 하나로 명확했다. 검출기가 없으면 코드로만
    추정한다.
    """
    from pathlib import Path as _P

    import guesskey as G
    fifths = None
    try:
        from ultralytics import YOLO

        import evaldet as E
        import probe as P
        w = _P(model_path or (_P(__file__).resolve().parent.parent
                              / "models" / "omr.pt"))
        if w.exists():
            big, _f = P.upscale(img.convert("RGB"))
            fifths = G.keysig_fifths(E.keysig_counts(YOLO(str(w)),
                                                    big.convert("L")))
    except Exception as e:                       # noqa: BLE001
        print(f"  조표 세기 실패: {e}", file=sys.stderr)
    key, conf, why = G.guess_with_keysig(texts, fifths)
    print(f"  원조성 {key}키로 추정 (근거 {why}, 확신도 {conf:.2f})",
          file=sys.stderr)
    return key


def main() -> None:
    ap = argparse.ArgumentParser(description="AI 코드 판독 (조각 격자 1회 호출)")
    ap.add_argument("image")
    ap.add_argument("detect", help="detect_chords.py 출력 JSON")
    ap.add_argument("-o", "--out", required=True)
    # **기본값을 두지 않는다.** 예전엔 "C"였는데, 원조성을 안 주면 그대로
    # 들어가 **조표가 틀린 악보**가 나왔다(실측: F키 악보를 -3반음 옮겼더니
    # C→A로 계산되어 ♯3(A장조)로 그려졌다. D장조는 ♯2다. 코드는 음정 차이만
    # 쓰므로 맞았고, 그래서 눈에 잘 안 보였다).
    ap.add_argument("--key", default=None,
                    help="원조성. 안 주면 조표와 코드로 추정한다")
    ap.add_argument("--model-path", default=None,
                    help="조표 세기용 검출기 (기본 models/omr.pt)")
    ap.add_argument("--title", default="")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--collage", help="격자 이미지를 저장 (디버그·API 호출 없이 확인)")
    ap.add_argument("--dry-run", action="store_true", help="API 호출 없이 격자만 만든다")
    args = ap.parse_args()

    img = load_image(args.image)
    with open(args.detect, encoding="utf-8") as f:
        detect = json.load(f)

    boxes = flatten_boxes(detect)
    collage, n = build_collage(img, boxes)
    print(f"조각 {n}개 → 격자 {collage.size[0]}x{collage.size[1]} "
          f"(이미지 토큰 약 {collage.size[0]*collage.size[1]//750})", file=sys.stderr)

    if args.collage:
        collage.save(args.collage)
        print(f"  격자 저장: {args.collage}", file=sys.stderr)
    if args.dry_run:
        return

    reads = read(collage, n, args.model)
    print(f"  판독 {len(reads)}개 / 요청 {n}개", file=sys.stderr)

    low = [r for r in reads if r.confidence < 0.9 and r.text.strip()]
    if low:
        print("  ⚠️  확인 권장(신뢰도 0.9 미만): " +
              ", ".join(f"#{r.index}={r.text}({r.confidence:.2f})" for r in low),
              file=sys.stderr)

    key = args.key
    if key is None:
        key = _guess_key(img, [r.text for r in reads if r.text.strip()],
                         args.model_path)
    meta = {"key": key, "pageCount": 1}
    if args.title:
        meta["title"] = args.title
    result = to_extraction(detect, boxes, reads, meta)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    total = sum(len(s["chords"]) for s in result["systems"])
    print(f"  → {args.out}  (코드 {total}개 / {len(result['systems'])}단)", file=sys.stderr)


if __name__ == "__main__":
    main()
