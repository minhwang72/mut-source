"""
**두 판독기 교차 검증** — 우리 struct 를 homr 결과와 마디 단위로 맞춘다.

규칙 기준(평가 eval/homr/ensemble.py, 105장): 교차하면 정답 통과가 8 → 11장,
11장 전부 원본과 일치. 독립된 두 판독기가 같게 읽은 마디는 거의 틀리지 않는다.

마디마다 (박이 맞다 = 음가 합이 한 마디):
  같게 읽음                → 확정. fit_page 가 찍은 표시(guessed)도 지운다 —
                             다른 판독기가 같은 답을 냈으면 찍은 게 아니다.
  우리만 안 맞고 homr 는 맞음 → homr 음가를 쓴다. **음높이는 우리 머리에서**
                             — 쉼표 아닌 음표 수가 같을 때만 짝지을 수 있다.
  둘 다 맞는데 다름          → 막는다(review). 우리가 머리를 또렷하게 본 자리를
                             homr 가 같은 길이 쉼표로 읽은 것만은 우리 쪽을 쓴다.
  그 밖                     → 우리 그대로.
단 수·마디 수가 서로 다르면 그 단은 비교하지 않는다(우리 판독 그대로).
"""
from __future__ import annotations

V = {"whole": 4.0, "half": 2.0, "quarter": 1.0, "eighth": 0.5, "16th": 0.25}
NAME = {v: k for k, v in V.items()}


def _tok(n: dict) -> str:
    v = V[n["duration"]] * (1.5 if n.get("dotted") else 1.0)
    return ("r" if n.get("rest") else "") + f"{v:g}"


def _len(seq) -> float:
    return sum(float(t.lstrip("r")) for t in seq)


def _dur(tok: str):
    """'0.75' → ('eighth', True). 우리가 못 그리는 길이면 None."""
    v = float(tok.lstrip("r"))
    if v in NAME:
        return NAME[v], False
    if v / 1.5 in NAME:
        return NAME[v / 1.5], True
    return None


def _units(notes: list[dict]) -> list[list[dict]]:
    """박을 차지하는 음(앞장선 음)마다 [그 음, 화음 구성음…]."""
    out: list[list[dict]] = []
    for n in notes:
        if n.get("chord") and out:
            out[-1].append(n)
        else:
            out.append([n])
    return out


def _adopt(units: list[list[dict]], theirs: list[str], mi: int) -> list[dict] | None:
    """homr 음가를 우리 음표에 입힌다. 음표 수가 다르면 None."""
    heads = [u for u in units if not u[0].get("rest")]
    if len(heads) != sum(1 for t in theirs if not t.startswith("r")):
        return None
    if any(_dur(t) is None for t in theirs):
        return None
    out, k = [], 0
    for t in theirs:
        name, dot = _dur(t)
        if t.startswith("r"):
            out.append({"measure": mi, "duration": name, "dotted": dot, "rest": True,
                        "tie": False, "chord": False, "beamGroup": -1, "homrFixed": True})
            continue
        for x in heads[k]:
            x["duration"], x["dotted"] = name, dot
            x["homrFixed"], x["guessed"] = True, False
        out.extend(heads[k])
        k += 1
    return out


def merge(struct: dict, homr: list[list[list[str]]] | None) -> dict:
    """
    struct 를 제자리에서 고친다. 반환: 통계.

    **마디를 쪽 전체에서 순서대로 짝짓는다.** 처음엔 '같은 단 번호의 같은 마디
    번호'끼리만 비교해서, 한쪽이 단을 하나 더 찾거나 세로줄 하나를 놓치면 그 단
    (또는 쪽)이 통째로 빠졌다 — 단 수가 다른 장 25, 마디 수가 다른 단 87(105장).
    이제는 두 마디 목록을 정렬한다(_align): 같으면 짝, 한쪽 두 마디를 이은 것이
    다른 쪽 한 마디와 같으면 '세로줄을 놓친 같은 내용', 나머지는 비슷할 때만 짝.
    """
    stat = {"agree": 0, "homr": 0, "ours": 0, "conflict": 0, "skipped": 0}
    systems = struct.get("systems") or []
    if not homr:
        stat["skipped"] = len(systems)
        return stat
    full = float(struct.get("beats") or 4)
    ours_m = []                       # (단, 마디번호)
    for si, sys_ in enumerate(systems):
        for mi in sorted({n["measure"] for n in sys_.get("notes") or []}):
            ours_m.append((si, mi))
    seq_o = [[_tok(u[0]) for u in _units([n for n in systems[si]["notes"] if n["measure"] == mi])]
             for si, mi in ours_m]
    seq_t = [m for sysm in homr for m in sysm]
    pairs = _align(seq_o, seq_t)       # 우리 마디 k → homr 토큰 목록 또는 None
    for si, sys_ in enumerate(systems):
        notes = sys_.get("notes") or []
        new: list[dict] = []
        for mi in sorted({n["measure"] for n in notes}):
            mine = [n for n in notes if n["measure"] == mi]
            k = ours_m.index((si, mi))
            theirs = pairs.get(k)
            if theirs is None:
                stat["skipped"] += 1
                new += mine
                continue
            new += _decide(sys_, mi, mine, theirs, full, stat)
        sys_["notes"] = new
        _drop_stale_count_review(sys_, full)
    return stat


def _decide(sys_, mi, mine, theirs, full, stat) -> list[dict]:
    """짝지은 한 마디를 판정한다 — 규칙은 모듈 머리말."""
    units = _units(mine)
    ours = [_tok(u[0]) for u in units]
    ok_o, ok_t = abs(_len(ours) - full) < 1e-6, abs(_len(theirs) - full) < 1e-6
    if ours == theirs:
        stat["agree"] += 1
        for n in mine:
            n["guessed"] = False
            n["crossChecked"] = True
        return mine
    if ok_t and not ok_o:
        got = _adopt(units, theirs, mi)
        if got is not None:
            stat["homr"] += 1
            return got
    if ok_o and ok_t and not _ours_saw_heads(units, theirs):
        stat["conflict"] += 1
        sys_.setdefault("review", []).append(f"마디 {mi}: 두 판독이 다르게 읽었습니다")
    else:
        stat["ours"] += 1
    return mine


# 짝지을 만큼 비슷한가 — 음가 토큰 순서가 이 비율 이상 겹쳐야 한다(엉뚱한 마디와
# 짝지어 homr 음가를 입히지 않게)
SIMILAR = 0.5


def _align(a: list[list[str]], b: list[list[str]]) -> dict[int, list[str]]:
    """
    우리 마디 목록 a 와 homr 마디 목록 b 를 정렬해 a 의 자리마다 짝 토큰을 준다.

    비용: 같음 0 · 비슷함(SIMILAR 이상) 1 · 건너뛰기 1 · 두 마디↔한 마디 이음이
    같음 0.5. 이음으로 짝지은 경우는 둘 다 '같음'으로 본다(그 마디 토큰을 그대로).
    """
    import difflib
    n, m = len(a), len(b)
    INF = float("inf")
    cost = [[INF] * (m + 1) for _ in range(n + 1)]
    back: list[list[tuple | None]] = [[None] * (m + 1) for _ in range(n + 1)]
    cost[0][0] = 0.0

    def sim(x, y):
        return x == y or difflib.SequenceMatcher(None, x, y).ratio() >= SIMILAR

    for i in range(n + 1):
        for j in range(m + 1):
            c = cost[i][j]
            if c == INF:
                continue
            steps = []
            if i < n and j < m:
                steps.append((i + 1, j + 1, 0.0 if a[i] == b[j] else (1.0 if sim(a[i], b[j]) else 1.9), "pair"))
            if i < n:
                steps.append((i + 1, j, 1.0, "skip_a"))
            if j < m:
                steps.append((i, j + 1, 1.0, "skip_b"))
            if i + 1 < n and j < m and a[i] + a[i + 1] == b[j]:
                steps.append((i + 2, j + 1, 0.5, "a2"))
            if i < n and j + 1 < m and a[i] == b[j] + b[j + 1]:
                steps.append((i + 1, j + 2, 0.5, "b2"))
            for i2, j2, w, how in steps:
                if c + w < cost[i2][j2]:
                    cost[i2][j2] = c + w
                    back[i2][j2] = (i, j, how)
    path = []
    i, j = n, m
    while (i, j) != (0, 0) and back[i][j] is not None:
        pi, pj, how = back[i][j]
        path.append((pi, pj, how))
        i, j = pi, pj
    diag = {(pi, pj) for pi, pj, how in path if how == "pair"}
    out: dict[int, list[str]] = {}
    for pi, pj, how in path:
        if how == "pair":
            # 비슷하면 짝. 많이 달라도 **앞뒤가 1:1 로 짝지어진 자리**면 같은
            # 마디다 — 위치가 고정돼 엉뚱한 마디일 수 없다(실측 day2sb-1 단7:
            # 'r2 r8 4' 대 'r2. r8 8' — 바로 homr 가 고쳐야 할 마디였다).
            before = (pi, pj) == (0, 0) or (pi - 1, pj - 1) in diag
            after = (pi, pj) == (n - 1, m - 1) or (pi + 1, pj + 1) in diag
            if sim(a[pi], b[pj]) or (before and after):
                out[pi] = b[pj]
        elif how == "a2":
            out[pi], out[pi + 1] = a[pi], a[pi + 1]
        elif how == "b2":
            out[pi] = a[pi]
    return out


def _drop_stale_count_review(sys_: dict, full: float) -> None:
    """
    **박이 다 맞게 됐으면 '개수 판독 불일치' 경고를 거둔다.**

    detstruct 는 그 경고를 '검출대로 읽은 마디 합이 틀릴 때만' 붙인다 —
    합이 맞으면 LLM 개수가 틀린 쪽이라서다(실측 93%). 교차 검증이 박을 고친
    뒤에도 병합 전 경고가 남아 그 단을 막고 있었다(set0816-1 등 5장).
    """
    per: dict = {}
    for n in sys_["notes"]:
        if not n.get("chord"):
            per[n["measure"]] = per.get(n["measure"], 0.0) + \
                V[n["duration"]] * (1.5 if n.get("dotted") else 1.0)
    if per and _beats_ok(per, full):
        rv = [r for r in sys_.get("review") or [] if not r.startswith("기존 개수 판독")]
        if rv:
            sys_["review"] = rv
        else:
            sys_.pop("review", None)


def _ours_saw_heads(units, theirs) -> bool:
    """우리가 음표로, homr 가 같은 길이 쉼표로 읽은 차이뿐이고 그 머리를 우리가
    검출로 봤으면(되살린 머리가 아니면) 우리 쪽이 맞다(실측 camp0814a-3 첫 음)."""
    ours = [_tok(u[0]) for u in units]
    if len(ours) != len(theirs):
        return False
    for u, a, b in zip(units, ours, theirs):
        if a == b:
            continue
        if a.lstrip("r") != b.lstrip("r") or not b.startswith("r") or a.startswith("r"):
            return False
        if u[0].get("headPromoted") or not u[0].get("head"):
            return False
    return True


def _beats_ok(per: dict, full: float) -> bool:
    """마디 합이 다 한 마디인가 — 단의 첫·끝 마디가 짧은 건 쪼개진 짝이나
    못갖춘마디일 수 있어 여기서 따지지 않는다(게이트의 짝 검사가 본다)."""
    ks = sorted(per)
    return all(abs(per[k] - full) < 1e-6 or (k in (ks[0], ks[-1]) and per[k] < full)
               for k in ks)
