#!/usr/bin/env python3
"""
**라벨링을 AI 두 개에게 맡긴다 — Claude Code CLI + Codex CLI.**

마디 그림과 두 판독(A=우리, B=homr)을 보여 주고 맞는 쪽을 고르게 한다(둘 다 틀리면
직접 적게). 결과는 data/label_queue/ai_labels.jsonl 에 AI 별로 남기고, **두 AI 가 같은
답을 낸 마디만** labels.jsonl 로 옮긴다(--merge). 한쪽만 답한 마디는 쓰지 않는다 —
AI 단독 판독은 악보 인식이 약하다는 연구가 있어(조사 보고서) 서로 확인시킨다.

    .venv/bin/python eval/ai_label.py claude 40     # Claude 로 40마디
    .venv/bin/python eval/ai_label.py codex 40      # Codex 로 40마디
    .venv/bin/python eval/ai_label.py --merge       # 둘이 같은 답만 labels.jsonl 로

외부 결제 API 를 쓰지 않는다 — 각 CLI 의 로그인(구독)으로 돈다.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time

ROOT = os.environ.get("LABEL_ROOT", "data/label_queue")
BATCH = 4
ORDER = {"불일치": 0, "짐작": 1, "자체수정": 2, "homr없음": 3}

PROMPT = """너는 악보 리듬 검수자다. 아래 이미지 {n}장은 각각 악보의 한 마디다.
이미지 위쪽은 오선 한 줄 전체(주황 박스가 그 마디), 아래쪽은 그 마디를 확대한 것이다.
확대 그림의 마디(양쪽 세로줄 사이)만 보고, 음표·쉼표의 길이를 왼쪽부터 순서대로 읽어라.

표기: 온음표 1, 2분 2, 4분 4, 8분 8, 16분 16. 쉼표는 앞에 r(예: r8). 점은 뒤에 .(예: 8.)
화음(같은 기둥에 머리 여럿)은 한 번만 센다. 붙임줄은 무시한다.
판단 요령: 속이 빈 머리=2분(기둥 있음)/온음표(기둥 없음), 묶음줄 1개·꼬리 1개=8분, 2개=16분,
머리 오른쪽 작은 점=점음표. 4/4 라면 마디 합은 보통 4박이다(못갖춘마디 제외).

다음이면 반드시 U: 셋잇단음표(숫자 3 표시)가 있음 · 확대 그림이 마디 하나 전체가 아님
(양쪽 세로줄이 안 보이거나 마디 일부만 보임) · 한 오선에 두 성부가 겹침.

각 마디마다 후보 A·B 가 있다. 그림과 정확히 같은 쪽을 고르고, 둘 다 틀리면 C 와 함께
직접 읽은 순서를 적어라. 확실하지 않으면 U.
{items}

출력은 JSON 배열 하나만(설명 없이):
[{{"id":"...","pick":"A|B|C|U","seq":"C 일 때만 공백으로 구분한 순서"}}]"""


def load_queue() -> list[dict]:
    q = [json.loads(l) for l in open(f"{ROOT}/queue.jsonl") if '"key"' in l]
    return sorted(q, key=lambda it: (ORDER.get(it["why"], 9), it["key"]))


def done_by(ai: str | None) -> set:
    """ai 가 답한 마디(None 이면 어느 AI 든) — 한도가 차면 다른 AI 가 남은 것만 잇는다."""
    p = f"{ROOT}/ai_labels.jsonl"
    if not os.path.exists(p):
        return set()
    return {d["key"] for d in map(json.loads, open(p)) if ai is None or d["ai"] == ai}


def ask(ai: str, batch: list[dict]) -> str:
    imgs = [os.path.abspath(f"{ROOT}/img/{it['key']}.png") for it in batch]
    items = "\n".join(
        f"- id={it['key']} 이미지={i + 1}번째{' (' + imgs[i] + ')' if ai == 'claude' else ''} "
        f"| A: {' '.join(it['ours'])} | B: {' '.join(it['homr']) or '(없음)'}"
        for i, it in enumerate(batch))
    prompt = PROMPT.format(n=len(batch), items=items)
    if ai == "claude":
        prompt += "\n\n각 이미지는 Read 도구로 위 경로를 열어 확인하라."
        cmd = ["claude", "-p", prompt, "--allowedTools", "Read",
               "--add-dir", os.path.abspath(f"{ROOT}/img")]
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}  # 구독으로만
    else:
        cmd = ["codex", "exec", "--skip-git-repo-check", "-s", "read-only",
               "-c", "model_reasoning_effort=\"low\""]
        for p in imgs:
            cmd += ["-i", p]
        cmd += ["--", prompt]
        env = dict(os.environ)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180, env=env,
                       stdin=subprocess.DEVNULL)  # 열린 stdin 이면 codex 가 끝없이 기다린다
    out = r.stdout + "\n" + r.stderr
    if re.search(r"usage.?limit|rate.?limit|hit your", out, re.I):
        raise RuntimeError("한도 소진")
    return r.stdout


def parse(text: str) -> list[dict]:
    m = re.findall(r"\[\s*\{.*?\}\s*\]", text, re.S)
    for chunk in reversed(m):
        try:
            return json.loads(chunk)
        except json.JSONDecodeError:
            continue
    return []


def run(ai: str, n: int, shard: str = "0/1") -> None:
    i, k = map(int, shard.split("/"))                   # 병렬 실행 — 서로 겹치지 않게 나눈다
    done = done_by(None)
    q = [it for it in load_queue() if it["key"] not in done][:n]
    q = [it for j, it in enumerate(q) if j % k == i]
    log = open(f"{ROOT}/ai_labels.jsonl", "a")
    for i in range(0, len(q), BATCH):
        batch = q[i:i + BATCH]
        try:
            ans = parse(ask(ai, batch))
        except subprocess.TimeoutExpired:
            # 가끔 한 묶음이 멈춘다 — 그 묶음만 건너뛰고 계속한다
            print(f"[{ai}] 시간 초과 — 이 묶음 건너뜀", flush=True)
            continue
        except Exception as e:                           # noqa: BLE001
            print(f"[{ai}] 멈춤: {e}"[:200], flush=True)
            return
        by = {a.get("id"): a for a in ans if isinstance(a, dict)}
        lines = []
        for it in batch:
            a = by.get(it["key"])
            if not a:
                continue
            pick = str(a.get("pick", "U")).upper()[:1]
            seq = (it["ours"] if pick == "A" else it["homr"] if pick == "B"
                   else str(a.get("seq") or "").split() if pick == "C" else None)
            lines.append(json.dumps({"key": it["key"], "ai": ai, "pick": pick, "seq": seq,
                                     "at": int(time.time())}, ensure_ascii=False) + "\n")
        log.write("".join(lines))                       # 한 번에 써야 병렬 실행끼리 줄이 안 섞인다
        log.flush()
        print(f"[{ai}] {i + len(batch)}/{len(q)}", flush=True)


def merge() -> None:
    by: dict = {}
    for d in map(json.loads, open(f"{ROOT}/ai_labels.jsonl")):
        by.setdefault(d["key"], {})[d["ai"]] = d
    agree = 0
    with open(f"{ROOT}/labels.jsonl", "a") as f:
        for k, v in by.items():
            a, b = v.get("claude"), v.get("codex")
            if a and b and a["seq"] and a["seq"] == b["seq"]:
                f.write(json.dumps({"key": k, "kind": "ai2", "answer": a["seq"],
                                    "at": int(time.time())}, ensure_ascii=False) + "\n")
                agree += 1
    print(f"두 AI 일치 {agree} / 양쪽 답 {sum(1 for v in by.values() if len(v) == 2)}")


if __name__ == "__main__":
    if sys.argv[1] == "--merge":
        merge()
    else:
        run(sys.argv[1], int(sys.argv[2]), *sys.argv[3:4])
