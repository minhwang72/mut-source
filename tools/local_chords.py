#!/usr/bin/env python3
"""
로컬 코드 판독 — 검출된 박스를 Tesseract로 한 조각씩 읽는다. **API 호출 0회.**

read_chords.py 와 같은 자리에 서지만 다른 계약을 가진다:

  · 조각을 격자로 묶지 않는다. Tesseract는 한 장에 여러 글자를 주면 읽는
    순서를 보장하지 않으므로 조각당 한 번씩 stdin→stdout 으로 돌린다.
    이미지는 파일로 떨어지지 않는다(서버 설계상 저장 금지).
  · **못 읽은 조각을 조용히 버리지 않는다.** 판독 실패도 결과에 실어
    보낸다 — 사용자가 그 자리에 코드가 있었다는 사실을 알아야 한다.
  · 코드인지 아닌지는 여기서 판단하지 않는다. 기존 Node 파서(src/cli.ts)에
    **한 번에 묶어** 물어본다 — AI 판독 경로와 같은 판정자를 쓴다.

확신도는 보수적으로 준다. Tesseract는 악보 글꼴(윗첨자·♭·♯)로 학습된 적이
없으므로 자기 점수를 그대로 믿으면 안 된다. 확실한 것만 높게 준다.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parent.parent

TESSERACT = os.environ.get("MUTE_TESSERACT", "/opt/homebrew/bin/tesseract")

# read_chords 와 같은 값. 작은 조각은 확대해야 읽힌다.
TILE_H = 130
PAD_RATIO = 0.18
# Tesseract는 글자가 테두리에 닿으면 못 읽는다. 흰 여백을 두른다.
MARGIN = 12
TIMEOUT = 8.0

# 코드 심볼에 실제로 나오는 글자만 남긴다. 열어 두면 오선 부스러기가
# 엉뚱한 글자로 읽혀 파서를 통과하는 가짜 코드가 생긴다.
WHITELIST = "ABCDEFGabdgijmnosu0123456789#+-/"

# Tesseract 점수를 그대로 쓰지 않는다. 악보 글꼴로 학습된 적이 없다.
CONF_SCALE = 0.85
# 이 아래면 "사람이 확인해야 한다"로 본다.
CONF_REVIEW = 0.80


class TesseractMissing(RuntimeError):
    pass


def _crop(img: Image.Image, b: dict) -> Image.Image:
    pad_x = max(2, int(b["w"] * PAD_RATIO))
    pad_y = max(2, int(b["h"] * PAD_RATIO))
    crop = img.crop((
        max(0, b["x"] - pad_x), max(0, b["y"] - pad_y),
        min(img.width, b["x"] + b["w"] + pad_x),
        min(img.height, b["y"] + b["h"] + pad_y),
    )).convert("L")
    scale = TILE_H / max(1, crop.height)
    crop = crop.resize((max(1, int(crop.width * scale)), TILE_H), Image.LANCZOS)
    canvas = Image.new("L", (crop.width + MARGIN * 2, crop.height + MARGIN * 2), 255)
    canvas.paste(crop, (MARGIN, MARGIN))
    return canvas


def _run(png: bytes, psm: str) -> tuple[str, float]:
    """한 조각을 읽는다. 반환: (글자, 0~1 확신도). 못 읽으면 ('', 0.0)."""
    try:
        proc = subprocess.run(
            [TESSERACT, "stdin", "stdout", "--psm", psm, "-l", "eng",
             "-c", f"tessedit_char_whitelist={WHITELIST}", "tsv"],
            input=png, capture_output=True, timeout=TIMEOUT,
        )
    except FileNotFoundError as e:                # noqa: BLE001
        raise TesseractMissing(f"tesseract 를 찾지 못했습니다: {TESSERACT}") from e
    except subprocess.TimeoutExpired:
        return "", 0.0
    if proc.returncode != 0:
        return "", 0.0

    words, confs = [], []
    for line in proc.stdout.decode("utf-8", "replace").splitlines()[1:]:
        cols = line.split("\t")
        if len(cols) < 12:
            continue
        text = cols[11].strip()
        if not text:
            continue
        try:
            c = float(cols[10])
        except ValueError:
            continue
        if c < 0:
            continue
        words.append(text)
        confs.append(c)
    if not words:
        return "", 0.0
    # 윗첨자(7·maj)는 다른 '단어'로 잡힌다 — 붙여 쓴다. 코드에는 공백이 없다.
    return "".join(words), min(confs) / 100.0


def validate(texts: list[str]) -> list[bool]:
    """
    코드 여부를 TS 코어 파서로 판정한다 — AI 경로와 **같은 판정자**다.

    한 번에 묶어 부른다. 조각마다 node를 띄우면 43개짜리 악보에서
    프로세스만 43번이다.
    """
    if not texts:
        return []
    proc = subprocess.run(
        ["node", "--disable-warning=ExperimentalWarning", "--experimental-strip-types",
         str(REPO / "src" / "cli.ts"), "validate"],
        input=json.dumps({"chords": texts}), capture_output=True, text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"코드 파서 호출 실패: {proc.stderr.strip()[:200]}")
    return [r["isChord"] for r in json.loads(proc.stdout)["results"]]


def read_boxes(img: Image.Image, boxes: list[dict]) -> list[dict]:
    """
    박스마다 {'text','confidence','ok','reason'} 를 낸다 — 입력과 같은 순서·길이.

    ok=False 인 항목도 버리지 않는다. 호출자가 "여기에 못 읽은 코드가 있다"고
    알릴 수 있어야 한다.
    """
    raw: list[tuple[str, float]] = []
    for b in boxes:
        png = _png(_crop(img, b))
        text, conf = _run(png, "7")
        if not text:
            # 한 줄로 못 읽으면 한 낱말로 다시 본다. 윗첨자가 붙은 심볼은
            # 줄 분할이 어긋나 빈 결과가 나오곤 한다.
            text, conf = _run(png, "8")
        raw.append((text, conf))

    valid = validate([t for t, _ in raw])
    out = []
    for (text, conf), ok in zip(raw, valid):
        c = round(min(1.0, conf * CONF_SCALE), 2)
        if not text:
            out.append({"text": "", "confidence": 0.0, "ok": False,
                        "reason": "글자를 읽지 못했습니다"})
        elif not ok:
            out.append({"text": text, "confidence": c, "ok": False,
                        "reason": f"코드로 해석되지 않습니다: {text!r}"})
        else:
            out.append({"text": text, "confidence": c, "ok": True,
                        "reason": None if c >= CONF_REVIEW else "판독 확신도가 낮습니다"})
    return out


def _png(im: Image.Image) -> bytes:
    import io
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def main() -> None:
    import argparse
    import sys

    ap = argparse.ArgumentParser(description="로컬 코드 판독 (Tesseract)")
    ap.add_argument("image")
    ap.add_argument("detect", help="detect_chords.py 출력 JSON")
    a = ap.parse_args()

    img = Image.open(a.image).convert("RGB")
    with open(a.detect, encoding="utf-8") as f:
        detect = json.load(f)
    boxes = [{"system": s["index"], **c}
             for s in detect["systems"] for c in sorted(s["chords"], key=lambda b: b["x"])]
    reads = read_boxes(img, boxes)
    bad = sum(1 for r in reads if not r["ok"])
    print(f"조각 {len(reads)}개 · 못 읽음 {bad}개", file=sys.stderr)
    print(json.dumps(reads, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
