#!/usr/bin/env python3
"""
**라벨(마디별 정답 리듬)을 검출기 학습 데이터로 바꾼다.**

라벨은 '8. 16 8 8' 같은 리듬 순서뿐이고, 검출기는 기호 상자가 필요하다. 그래서
그 마디의 검출 결과(낮은 점수 후보까지)에서 정답에 맞는 상자를 골라 마디 하나를
학습 그림으로 만든다. **확실히 맞출 수 있는 마디만** 쓴다:
  · 음표 머리 수가 정답과 같을 것(다르면 어느 머리가 헛것·빠진 것인지 모른다)
  · 꼬리·묶음줄 단계(8분/16분)가 바뀌지 않을 것 — 바뀌면 그 상자가 틀려 있다
  · 정답의 쉼표·붙임점마다 그 자리에 후보 상자가 있을 것(없으면 위치를 모른다)
고치는 것은 머리 종류(빈 머리/찬 머리), 쉼표 추가·종류, 붙임점 추가 — 실패의 주류다.

    MUTE_HOMR_BIN=.homr-venv/bin/homr .venv/bin/python eval/label_build.py \\
        악보샘플/학습용_이미지 data/label_queue data/real_labeled
"""
from __future__ import annotations

import json
import os
import sys

sys.path[:0] = ["tools", "server", "eval"]

import devcache  # noqa: E402

devcache.install()

import evaldet as E  # noqa: E402
import local_reader as LR  # noqa: E402
import sheetcv as cv  # noqa: E402
from pseudo_label import CLS, TARGET, _cap  # noqa: E402  (detect_guided 엿보기 포함)

HEAD = {"1": "notehead_whole", "2": "notehead_half"}
REST = {"1": "rest_whole", "2": "rest_half", "4": "rest_quarter", "8": "rest_8th",
        "16": "rest_16th"}
LEVEL = {"8": 1, "16": 2, "32": 3}
D = {"whole": "1", "half": "2", "quarter": "4", "eighth": "8", "16th": "16", "32nd": "32"}


def units(seq: list[str]) -> list[tuple[bool, str, bool]]:
    out = []
    for t in seq:
        rest = t.startswith("r")
        t = t.lstrip("r")
        out.append((rest, t.rstrip("."), t.endswith(".")))
    return out


def cx(b):
    return b["x"] + b["w"] / 2


def build_measure(lab, heads, cands, x0, x1, sp, top, bot):
    """정답 units 와 우리 머리·후보 상자 → 상자 목록. 맞출 수 없으면 None."""
    notes = [u for u in lab if not u[0]]
    if len(notes) > len(heads):
        # 머리를 놓친 마디 — 낮은 점수 후보 중 기존 머리와 안 겹치는 것이 **딱 모자란
        # 만큼** 있으면 그것을 머리로 넣는다(많거나 적으면 어느 것인지 몰라 포기)
        def far(b):
            return all(abs(cx(b) - cx(h["head"])) > sp * 0.6 for h in heads)
        extra = [b for b in cands if b["class"].startswith("notehead") and far(b)
                 and top - sp * 4 < b["y"] + b["h"] / 2 < bot + sp * 4]
        # 같은 자리 겹친 후보는 하나로
        extra.sort(key=lambda b: -b["conf"])
        pick = []
        for b in extra:
            if all(abs(cx(b) - cx(p)) > sp * 0.6 for p in pick):
                pick.append(b)
        if len(pick) != len(notes) - len(heads):
            return None
        heads = sorted(heads + [{"duration": None, "head": {k: b[k] for k in ("x", "y", "w", "h")}}
                                for b in pick], key=lambda h: cx(h["head"]))
    if len(notes) != len(heads):
        return None
    out = []
    # 머리 — 종류만 정답대로. 꼬리 단계가 바뀌면 포기
    for (rest, base, dot), h in zip(notes, heads):
        if h["duration"] is not None and \
                LEVEL.get(D.get(h["duration"], "4"), 0) != LEVEL.get(base, 0):
            return None
        out.append({"class": HEAD.get(base, "notehead_filled"), **h["head"]})
        col = [h["head"], *h.get("members", [])]
        # 판독이 놓친 화음 구성음 — 라벨에 없으면 학습이 그 머리를 배경으로 배운다.
        # 같은 기둥(가로 0.5칸 안)의 후보 머리 중 기존 머리와 세로로 안 겹치는 것을 채운다
        for b in sorted(cands, key=lambda b: -b["conf"]):
            if (b["class"].startswith("notehead") and b["conf"] >= 0.1
                    and abs(cx(b) - cx(h["head"])) < sp * 0.5
                    and top - sp * 4 < b["y"] + b["h"] / 2 < bot + sp * 4
                    and all(abs(b["y"] + b["h"] / 2 - m["y"] - m["h"] / 2) > sp * 0.6 for m in col)):
                col.append({k: b[k] for k in ("x", "y", "w", "h")})
        for m in col[1:]:
            out.append({"class": HEAD.get(base, "notehead_filled"), **m})
    # 순서상 각 단위의 왼쪽 경계·오른쪽 경계(이웃 머리 사이)를 정한다
    xs = [cx(h["head"]) for h in heads]
    ni = 0
    used = set()
    last_rest = -1e9
    for i, (rest, base, dot) in enumerate(lab):
        lo = xs[ni - 1] if ni > 0 else x0
        hi = xs[ni] if ni < len(xs) else x1
        if rest:
            # 마디 안쪽만(옆 마디 쉼표·세로줄·도돌이 점을 잡지 않게), 이미 쓴 쉼표와 같은
            # 자리 후보는 빼고, 같은 구간에 쉼표가 여럿이면 **왼쪽부터** 순서대로 쓴다
            c = [b for b in cands if b["class"].startswith("rest")
                 and max(lo, x0 + sp * 0.5) < cx(b) < min(hi, x1 - sp * 0.5)
                 and cx(b) > last_rest + sp * 0.5
                 and top - sp * 2 < b["y"] + b["h"] / 2 < bot + sp * 2]
            if not c:
                return None
            left = min(cx(b) for b in c)
            b = max((b for b in c if cx(b) < left + sp * 0.5), key=lambda b: b["conf"])
            last_rest = cx(b)
            used.add(id(b))
            out.append({**{k: b[k] for k in ("x", "y", "w", "h")}, "class": REST.get(base, "rest_quarter")})
            anchor = b
        else:
            anchor = heads[ni]["head"]
            ni += 1
        if dot:
            ax = anchor["x"] + anchor["w"]
            nxt = xs[ni] if ni < len(xs) else x1
            ay = anchor["y"] + anchor["h"] / 2
            c = [b for b in cands if b["class"] == "aug_dot" and id(b) not in used
                 and ax - sp * 0.3 < cx(b) < min(nxt, ax + sp * 2)
                 and abs(b["y"] + b["h"] / 2 - ay) < sp * 1.2]
            if not c:
                return None
            b = max(c, key=lambda b: b["conf"])
            used.add(id(b))
            out.append({**{k: b[k] for k in ("x", "y", "w", "h")}, "class": "aug_dot"})
    return out


def main(src: str, qdir: str, out: str) -> None:
    from PIL import Image
    os.makedirs(f"{out}/images/train", exist_ok=True)
    os.makedirs(f"{out}/labels/train", exist_ok=True)
    q = {}
    for l in open(f"{qdir}/queue.jsonl"):
        d = json.loads(l)
        if "key" in d:
            q[d["key"]] = d
    lab = {}
    for l in open(f"{qdir}/labels.jsonl"):
        d = json.loads(l)
        if d.get("answer") and d.get("kind") in ("ours", "homr", "custom", "ai2", "ai1v"):
            lab[d["key"]] = d["answer"]
    by_page: dict = {}
    for k, ans in lab.items():
        if k in q:
            by_page.setdefault(q[k]["page"], []).append((q[k], ans))
    stat = {"labels": len(lab), "built": 0, "skipped": 0}
    import local_reader  # noqa: F401
    model = None
    for page, items in sorted(by_page.items()):
        _cap.clear()
        png = open(f"{src}/{page}.png", "rb").read()
        try:
            ex = LR.read_sheet_local(png)
        except Exception:                              # noqa: BLE001
            stat["skipped"] += len(items)
            continue
        st, geo = ex.get("struct") or {}, ex.get("geometry") or {}
        if "img" not in _cap or not st.get("systems"):
            stat["skipped"] += len(items)
            continue
        big = _cap["img"].convert("L")
        boxes = _cap["boxes"]
        if model is None:
            model = LR._model(LR.model_path())
        cands, _ = E.detect_by_staff(model, big, conf=0.05)
        _ink, staves = cv.find_staves_best(big)
        sp = cv.median_spacing(staves)
        for it, ans in items:
            si, mi = it["system"], it["measure"]
            if si >= len(st["systems"]) or si >= len(staves):
                stat["skipped"] += 1
                continue
            g = geo["systems"][si]
            edges = [g.get("left", 0), *(g.get("bars") or []), g.get("right", big.width)]
            if mi >= len(edges):
                stat["skipped"] += 1
                continue
            x0, x1 = edges[mi - 1], edges[mi]
            stf = staves[si]
            notes = [n for n in st["systems"][si]["notes"] if n["measure"] == mi]
            heads = []
            for n in notes:
                if n.get("rest") or not n.get("head"):
                    continue
                if n.get("chord") and heads:
                    heads[-1].setdefault("members", []).append(n["head"])
                else:
                    heads.append({"duration": n["duration"], "head": n["head"]})
            heads.sort(key=lambda h: cx(h["head"]))
            mine = [b for b in cands if x0 - sp < cx(b) < x1 + sp]
            got = build_measure(units(ans), heads, mine, x0, x1, sp, stf.top, stf.bottom)
            if got is None:
                stat["skipped"] += 1
                continue
            # 꼬리·묶음줄·붙임줄·임시표는 본 검출 그대로(이 마디 안)
            keep = {"flag_8th", "flag_16th", "beam1", "beam2", "tie", "accidental_sharp",
                    "accidental_flat", "accidental_natural", "timesig", "clef_g"}
            got += [{k: b[k] for k in ("class", "x", "y", "w", "h")} for b in boxes
                    if b["class"] in keep and x0 - sp * 0.5 < cx(b) < x1 + sp * 0.5
                    and stf.top - sp * 5 < b["y"] + b["h"] / 2 < stf.bottom + sp * 6]
            cy0 = max(0, int(stf.top - sp * 5)); cy1 = min(big.height, int(stf.bottom + sp * 6))
            cx0 = max(0, int(x0 - sp * 0.6)); cx1 = min(big.width, int(x1 + sp * 0.6))
            crop = big.crop((cx0, cy0, cx1, cy1))
            k = TARGET / sp
            crop = crop.resize((max(1, round(crop.width * k)), max(1, round(crop.height * k))),
                               Image.LANCZOS)
            W, H = cx1 - cx0, cy1 - cy0
            lines = []
            for b in got:
                c = CLS.get(b["class"])
                if c is None:
                    continue
                bx0 = max(0, b["x"] - cx0); bx1 = min(W, b["x"] + b["w"] - cx0)
                by0 = max(0, b["y"] - cy0); by1 = min(H, b["y"] + b["h"] - cy0)
                if bx1 <= bx0 or by1 <= by0:
                    continue
                lines.append(f"{c} {(bx0 + bx1) / 2 / W:.6f} {(by0 + by1) / 2 / H:.6f} "
                             f"{(bx1 - bx0) / W:.6f} {(by1 - by0) / H:.6f}")
            name = it["key"]
            crop.save(f"{out}/images/train/{name}.png")
            open(f"{out}/labels/train/{name}.txt", "w").write("\n".join(lines) + "\n")
            stat["built"] += 1
        print(page, stat, flush=True)
    print("끝", stat)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
