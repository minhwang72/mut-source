#!/usr/bin/env python3
"""
**라벨링할 마디 목록을 만든다** — 학습용 콘티에서 두 판독이 갈리거나 막힌 마디만.

두 판독기가 같게 읽은 마디는 이미 라벨이 있다(eval/pseudo_label.py). 엔진을 올리려면
**지금 실패하는 마디의 정답**이 필요하므로, 그 마디만 사람에게 묻는다.

마디마다 남기는 것: 쪽 · 단 · 마디 번호, 마디 그림(단 전체 + 확대), 우리 읽기,
homr 읽기(짝지어졌으면), 막힌 이유. 그림은 data/label_queue/ 에만 둔다(git 제외).
외부 API 를 부르지 않는다(로컬 판독 + 저장된 homr 결과).

    MUTE_HOMR_BIN=.homr-venv/bin/homr .venv/bin/python eval/label_queue.py \\
        악보샘플/학습용_이미지 data/label_queue
"""
from __future__ import annotations

import glob
import json
import os
import sys

sys.path[:0] = ["tools", "server"]

import devcache  # noqa: E402

devcache.install()

import crosscheck as C  # noqa: E402
import homr_runner as H  # noqa: E402
import local_reader as LR  # noqa: E402

D = {"whole": "1", "half": "2", "quarter": "4", "eighth": "8", "16th": "16", "32nd": "32"}
BEATS = {"1": 4, "2": 2, "4": 1, "8": 0.5, "16": 0.25, "32": 0.125}


def tok(n: dict) -> str:
    return ("r" if n.get("rest") else "") + D.get(n["duration"], "?") + ("." if n.get("dotted") else "")


def homr_tok(t: str) -> str:
    """'0.75' → '8.' · 'r1' → 'r4' (우리 표기로)."""
    rest = t.startswith("r")
    v = float(t.lstrip("r"))
    for k, b in BEATS.items():
        if abs(v - b) < 1e-6:
            return ("r" if rest else "") + k
        if abs(v - b * 1.5) < 1e-6:
            return ("r" if rest else "") + k + "."
    return t


def main(src: str, out: str) -> None:
    from PIL import Image, ImageDraw
    os.makedirs(f"{out}/img", exist_ok=True)
    qpath = f"{out}/queue.jsonl"
    done = set()
    if os.path.exists(qpath):
        done = {json.loads(l)["page"] for l in open(qpath)}
    q = open(qpath, "a")
    for f in sorted(glob.glob(f"{src}/*.png")):
        page = os.path.basename(f)[:-4]
        if page in done:
            continue
        png = open(f, "rb").read()
        try:
            ex = LR.read_sheet_local(png)
            homr = H.read(png)
        except Exception as e:                       # noqa: BLE001
            print(f"{page}: 실패 {e}"[:120], flush=True)
            continue
        st, geo = ex.get("struct") or {}, ex.get("geometry") or {}
        if not st.get("systems") or len(st["systems"]) != len(geo.get("systems") or []):
            q.write(json.dumps({"page": page, "skip": "단 수 불일치"}, ensure_ascii=False) + "\n")
            continue
        # homr 짝을 마디마다 기록하려고 merge 전에 정렬 결과를 따로 얻는다
        ours_m, seqs = [], []
        for si, s in enumerate(st["systems"]):
            for mi in sorted({n["measure"] for n in s["notes"]}):
                ours_m.append((si, mi))
                seqs.append([C._tok(u[0]) for u in C._units(
                    [n for n in s["notes"] if n["measure"] == mi])])
        theirs = {}
        if homr:
            seq_t = [m for sm in homr["dur"] for m in sm]
            pairs, _at, _sk = C._align(seqs, seq_t)
            theirs = {ours_m[k]: v for k, v in pairs.items()}
            C.merge(st, homr)
        scale = float(geo.get("scale") or 1.0)
        img = Image.open(f).convert("RGB")
        big = img.resize((round(img.width * scale), round(img.height * scale))) if scale > 1 else img
        n_items = 0
        for si, (s, g) in enumerate(zip(st["systems"], geo["systems"])):
            edges = [g.get("left", 0), *(g.get("bars") or []), g.get("right", big.width)]
            top, bot = g.get("staffTop", 0), g.get("staffBottom", 0)
            sp = max(1.0, (bot - top) / 4)
            y0, y1 = max(0, int(top - sp * 4)), min(big.height, int(bot + sp * 4))
            review = " ".join(s.get("review") or [])
            for mi in sorted({n["measure"] for n in s["notes"]}):
                ns = [n for n in s["notes"] if n["measure"] == mi and not n.get("chord")]
                agreed = all(n.get("crossChecked") for n in ns) and f"마디 {mi}:" not in review
                if agreed and not any(n.get(k) for n in ns for k in C.UNSURE):
                    continue
                if mi - 1 >= len(edges) - 1:
                    continue
                x0, x1 = int(edges[mi - 1]), int(edges[mi])
                if x1 - x0 < sp * 2:
                    continue
                key = f"{page}_s{si}_m{mi}"
                strip = big.crop((0, y0, big.width, y1))
                zoom = big.crop((max(0, x0 - int(sp * 2)), y0, min(big.width, x1 + int(sp * 2)), y1))
                k = 900 / max(1, zoom.width)
                zoom = zoom.resize((900, max(1, int(zoom.height * k))))
                k2 = 900 / strip.width
                strip = strip.resize((900, max(1, int(strip.height * k2))))
                d = ImageDraw.Draw(strip, "RGBA")
                d.rectangle([x0 * k2, 0, x1 * k2, strip.height - 1], fill=(255, 200, 0, 60),
                            outline=(220, 120, 0, 255), width=2)
                canvas = Image.new("RGB", (900, strip.height + zoom.height + 8), "white")
                canvas.paste(strip, (0, 0)); canvas.paste(zoom, (0, strip.height + 8))
                canvas.save(f"{out}/img/{key}.png")
                ours = [tok(n) for n in ns]
                th = [homr_tok(t) for t in theirs.get((si, mi), [])]
                why = ("짐작" if any(n.get("guessed") for n in ns) else
                       "불일치" if th and th != ours else
                       "homr없음" if not th else "자체수정")
                q.write(json.dumps({"key": key, "page": page, "system": si, "measure": mi,
                                    "box": [x0, y0, x1, y1], "scale": scale,
                                    "ours": ours, "homr": th, "why": why},
                                   ensure_ascii=False) + "\n")
                n_items += 1
        q.write(json.dumps({"page": page, "items": n_items}, ensure_ascii=False) + "\n")
        q.flush()
        print(f"{page}: {n_items}마디", flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
