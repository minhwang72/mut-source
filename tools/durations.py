"""
검출 상자만으로 음가를 읽는다 — LLM 없이.

왜 필요한가: 구조 판독(LLM)의 출력 대부분이 음가와 마디 수다. 음가만
정확히 읽으면 마디 경계는 4박 누적으로 산술 유도할 수 있어(실측: 28단
28단 모두 재현) LLM이 할 일이 거의 남지 않는다.

핵심은 **줄기 쪽 모서리**다. 빔은 줄기 끝에 붙으므로 머리 중심이 아니라
줄기가 선 모서리로 겹수를 물어야 한다 — 붙임점8분+16분처럼 겹빔이 반쪽만
있는 리듬은 중심으로 물으면 갈리지 않는다(실측: 왼쪽 모서리로 4/4 정답,
중심으로는 갈리지 않음).
"""
from __future__ import annotations

LEVEL_DUR = {0: "quarter", 1: "eighth", 2: "16th"}
BEAM_LEVEL = {"beam1": 1, "beam2": 2}
FLAG_LEVEL = {"flag_8th": 1, "flag_16th": 2}


def _cy(b) -> float:
    return b["y"] + b["h"] / 2


def _level(head, marks, spacing: float) -> int:
    """머리 하나에 붙은 빔·꼬리의 겹수. 못 찾으면 0."""
    return _level_and_beam(head, marks, spacing)[0]


def beam_runs(marks, spacing: float) -> list[dict]:
    """
    **x로 맞닿는 빔 상자를 하나로 잇는다.** 한 묶음인데 상자가 갈라져 나온다 —
    16분음표에서 1겹 빔과 2겹 빔이 겹치는 구간은 잉크가 두꺼워 검출기가
    beam2 로 따로 떼고, 그 바람에 1겹 상자가 짝의 오른쪽 줄기에 닿기 전에
    끊긴다. 그러면 그 음표가 혼자 남아 빔이 통째로 사라진다
    (실측 day2sb-1: 묶음 70개 중 49개가 1개짜리 → 102음 중 42음만 묶였다).

    맞닿음 판정이 안전한 이유: 한 묶음 안의 상자는 0.4px 이내로 겹치는데,
    다른 묶음 사이는 3칸 이상 떨어진다(5장 150쌍 실측 — 그 사이 값이 없다).
    그래서 반 칸까지 잇는다 — 0.25칸이면 상자가 6.6px(0.37칸) 벌어진
    `8 16 16` 이 [8,16]+[16] 두 묶음이 됐다(실측 now0918-11 단2 마디4).
    """
    tol = spacing * 0.5
    runs: list[dict] = []
    for m in sorted((b for b in marks if b["class"] in BEAM_LEVEL),
                    key=lambda b: b["x"]):
        cy = _cy(m)
        for r in runs:
            if (m["x"] <= r["x1"] + tol and m["x"] + m["w"] >= r["x0"] - tol
                    and abs(cy - r["cy"]) <= spacing * 1.5):
                r["x0"] = min(r["x0"], m["x"])
                r["x1"] = max(r["x1"], m["x"] + m["w"])
                r["cy"] = (r["cy"] * r["n"] + cy) / (r["n"] + 1)
                r["n"] += 1
                break
        else:
            runs.append({"x0": m["x"], "x1": m["x"] + m["w"],
                         "cy": cy, "n": 1})
    return runs


def _level_and_beam(head, marks, spacing: float,
                    runs=None) -> tuple[int, int]:
    """
    (겹수, **어느 빔 묶음에 붙었는지**). 빔을 못 찾으면 (겹수, -1).

    왜 빔 식별이 필요한가: 재조판할 때 빔 묶음을 지어내면 원본과 그림이
    달라진다 — "키만 바뀐 같은 악보"가 목표인데 꼬리 묶음이 제멋대로면
    다른 악보로 보인다. 원본에서 검출한 빔 상자를 그대로 묶음 기준으로 쓴다.
    꼬리(flag)는 혼자 서므로 묶음이 아니다(-1).
    """
    tol = spacing * 0.25
    # 세로 범위를 좁게 잡으면 **도약이 큰 묶음**의 바깥 음표를 놓친다.
    # 6칸으로 재면 95.0%, 16칸이면 100%였다(정답 상자 15,479음 기준).
    # 검출은 단별 띠 안에서만 하므로 이웃 단의 빔이 섞이지 않는다.
    near = spacing * 16.0
    best = 0
    for m in marks:
        lv = BEAM_LEVEL.get(m["class"]) or FLAG_LEVEL.get(m["class"])
        if not lv:
            continue
        dy = _cy(m) - _cy(head)
        if abs(dy) > near or abs(dy) < spacing * 0.4:
            continue
        # 빔이 아래에 있으면 줄기는 아래 = 머리 왼쪽, 위면 머리 오른쪽
        sx = head["x"] if dy > 0 else head["x"] + head["w"]
        if m["x"] - tol <= sx <= m["x"] + m["w"] + tol and lv > best:
            best = lv

    group, bestdy = -1, None
    for i, r in enumerate(beam_runs(marks, spacing) if runs is None else runs):
        dy = r["cy"] - _cy(head)
        if abs(dy) > near or abs(dy) < spacing * 0.4:
            continue
        sx = head["x"] if dy > 0 else head["x"] + head["w"]
        if r["x0"] - tol <= sx <= r["x1"] + tol and (
                bestdy is None or abs(dy) < bestdy):
            group, bestdy = i, abs(dy)
    return best, group


# 점수는 **머리의 잉크 농도로 나눈 값**이다. 절대 밝기로 재면 인쇄 농도와
# 해상도에 따라 문턱이 흔들린다 — 머리는 점 바로 옆에 있는 순수 잉크라
# 그 페이지의 "가장 진한 검정"을 공짜로 알려 준다.
# 문턱을 4장으로 훑어 정했다(붙임점 개수, 정답 대비):
#           0.55  0.50  0.45  0.40
#   마커스(9)   8     8     8     9
#   위싱(6)     8     8     8     8
#   DAY2(24)   23    24    24    25
#   6/8 저해상    1     2    10    12
# 0.45 는 4/4 세 장을 그대로 두거나 개선하면서(DAY2 정확) 저해상도 악보의
# 흐린 점을 살린다. 0.40 은 DAY2 가 하나 넘친다.
DOT_SCORE = 0.55
# 속 빈 머리로 보려면 테두리 좌우가 이만큼은 잉크여야 한다 (× 머리 제외)
SIDE_INK_MIN = 0.30
# 상자 안 가장 밝은 쪽과 가장 진한 쪽 차이가 이보다 작으면 종이가 없는 것이다
SOLID_SPAN = 40.0
# 속 비움 점수가 이보다 낮으면 가운데가 진하다 — 꽉 찬 머리(실측 0.004~0.012)
DARK_CORE = 0.10
# 가운데 영역 중 종이 쪽 화소가 이만큼이면 구멍이 있다고 본다
HOLE_MIN = 0.10
# 회색지대: 점 같기는 한데 문턱을 못 넘은 구간. 저해상도 악보(원본 간격 8px)
# 에서는 붙임점 잉크가 흐려 점수가 통째로 내려앉는다 — 6/8 한 장에서 108개
# 중 문턱을 넘는 건 1개뿐인데 0.45~0.55 에 9개가 몰려 있었다.
# 그렇다고 문턱 자체를 0.45 로 낮추면 DAY2 가 마디 45→43 으로 회귀한다.
# 그래서 문턱은 두고, **마디 합이 모자랄 때만** 이 구간을 후보로 쓴다
# (fitdur.promote_dots). 이미 합이 맞는 마디는 건드릴 일이 없으므로
# 오탐이 새로 생기지 않는다.
DOT_GRAY = 0.40


CURVE = {"tie", "tie_stop", "slur", "slur_stop"}


def _occupancy(boxes, shape, spacing: float):
    """붙임점 말고 검출된 기호 자리를 가린다."""
    import numpy as np

    m = np.zeros(shape, bool)
    pad = spacing * 0.12
    for b in boxes:
        if b["class"] == "aug_dot":      # 점 자체를 가리면 안 된다
            continue
        # **곡선은 상자로 가리지 않는다.** 이음줄은 가는 획인데 상자는 아치
        # 전체라, 긴 이음줄 하나가 그 아래 붙임점 자리를 통째로 지웠다
        # (실측 camp0814a-3 단3: 점2분의 점 0.61 이 424×46 상자에 묻혀 2분이
        # 됐고, fit_page 가 8분 둘을 4분으로 늘려 합을 맞췄다 — 틀린 악보).
        # 획 위인지는 `_on_curve` 가 따로 가린다.
        if b["class"] in CURVE:
            continue
        y0, y1 = max(0, int(b["y"] - pad)), min(shape[0], int(b["y"] + b["h"] + pad))
        x0, x1 = max(0, int(b["x"] - pad)), min(shape[1], int(b["x"] + b["w"] + pad))
        m[y0:y1, x0:x1] = True
    return m


def _on_curve(xi: int, yi: int, curves, spacing: float, head) -> bool:
    """
    후보가 곡선(붙임줄·이음줄)의 획 위인가.

    곡선의 꼭대기는 붙임점 자리(머리 오른쪽 반 칸 위)에 정확히 온다 —
    실측: 위싱에서 이렇게 생긴 가짜 붙임점이 2개 있었다.

    단, **이 머리에서 출발하는 곡선은 반증이 될 수 없다.** 곡선의 왼쪽 끝은
    정의상 이 머리의 붙임점 자리를 지나가므로, 그걸로 지우면 "붙임줄로 이어지는
    붙임점 음표"는 붙임점을 영영 못 얻는다 — 실측(set0802-7 단1): 붙임점 4분음표
    두 개의 점수가 0.470·0.563 인데 이 필터가 둘 다 0 으로 만들었다.
    꼭대기가 문제인 경우는 곡선이 이 머리보다 **왼쪽에서** 시작할 때다.
    """
    for c in curves or ():
        if c["x"] >= head["x"]:
            continue
        if not (c["x"] <= xi <= c["x"] + c["w"]):
            continue
        top, bot = c["y"], c["y"] + c["h"]
        # **상자 바깥이면 반증이 아니다.** 아래 줄의 `yi - top <= band` 는
        # 후보가 상자 **위**에 있으면 음수가 되어 늘 참이었다 — 그래서 그
        # 단 어디의 이음줄이든 x 만 걸치면 위쪽 붙임점 자리를 통째로
        # 막았다(실측 camp0814c-04 단3 마디2: 또렷한 붙임점인데 후보 12곳이
        # 전부 걸려 점수 0.00, 그 마디가 0.5박 모자란 채 fit_page 로 갔다).
        if not (top <= yi <= bot):
            continue
        # 획은 상자의 위·아래 가장자리에 있으므로 그 띠만 뺀다. 상자 전체를
        # 가리면 아치 안쪽의 진짜 붙임점까지 사라진다. 0.35~0.50을 재 봤고
        # 0.40이 가장 좋았다(위싱 98.0% → 99.0%, 마커스·DAY2 그대로).
        # **띠를 반 칸으로 묶는다.** 긴 이음줄은 상자가 높아 0.40배가
        # 상자를 통째로 덮는다 — 실측 camp0814c-04 단3 마디2: 눈에 또렷한
        # 붙임점인데 후보 자리 12곳이 **전부** 이 조건에 걸려 점수가
        # 0.00 이었고, 그 마디가 0.5박 모자란 채 fit_page 로 넘어갔다.
        # 획 자체는 2~3px 라 반 칸이면 "꼭대기가 붙임점 자리에 온" 경우를
        # 잡기에 충분하다.
        band = min(max(2.0, c["h"] * 0.40), spacing * 0.5)
        if yi - top <= band or bot - yi <= band:
            return True
    return False


def _dot_score(head, g, occ, spacing: float, curves=None, ns=None,
               lines=None) -> tuple[float, float]:
    """
    머리 오른쪽 붙임점 자리를 **화소로 직접 잰다**.

    왜 검출기로 안 되는가(실측): 점 상자는 오선 간격의 0.40배라 검출 입력에서
    2.6px밖에 안 된다. 학습해도 재현율 0.186에 그쳤고, 실제 악보의 점 9개 중
    1개만 잡혔다. 대신 **머리 위치를 이미 아니** 점이 있을 자리를 직접 보면
    된다.

    **자리는 실제 악보로 재야 한다.** 합성 227개로 재서 0.46~0.54칸을 보고
    있었는데, 실제 악보 181개를 재 보니 가로 중앙값이 **0.70칸**이고
    5~95% 가 0.55~0.92 였다 — 분포가 `0.6:44 0.7:88 0.8:28 0.9:11` 이라
    옛 범위에 드는 건 181개 중 6개뿐이었다. 즉 **거의 항상 엉뚱한 곳을
    보고 있었고**, 그래서 이 점수는 실제 악보에서 죽어 있었다.
    세로는 중앙값 -0.37칸(머리가 줄 위면 위로 반 칸 올라간다).
    넓게 훑으면 기둥·이음줄이 걸리므로 분포 안쪽만 본다.

    점수 = min(종이보다 어두운 정도, 둘레보다 어두운 정도 × 2.2).
    둘레 조건이 기둥·오선을 걸러 낸다 — 그것들은 둘레도 어둡다.
    점수는 머리의 잉크 농도로 나눈 비율이라 인쇄 농도·해상도에 안 흔들린다.
    """
    import numpy as np

    r = max(1.0, spacing * 0.20)
    R = max(2.0, spacing * 0.55)
    hx, cy = head["x"] + head["w"], head["y"] + head["h"] / 2
    hb = g[int(head["y"]):int(head["y"] + head["h"]) + 1,
           int(head["x"]):int(head["x"] + head["w"]) + 1]
    if hb.size == 0:
        return 0.0
    # **속 빈 머리는 가운데가 희다.** 테두리까지 포함해 가장 진한 쪽을 잉크로 본다
    ink = float(np.percentile(hb, 10))
    best, best_run = 0.0, 0.0
    for dy in (0.0, -0.35, -0.6):
        for ddx in (0.60, 0.70, 0.80, 0.90):
            xi, yi = int(hx + spacing * ddx), int(cy + spacing * dy)
            if not (R < xi < g.shape[1] - R and R < yi < g.shape[0] - R):
                continue
            if occ[yi, xi] or _on_curve(xi, yi, curves, spacing, head):
                continue
            # **붙임점은 줄 위에 오지 않는다 — 언제나 칸에 찍힌다**(조판 규칙).
            # 줄에 걸친 머리는 같은 높이 후보가 줄 위에 떨어져 줄 잉크를
            # 점으로 셌다. 오선 제거가 실패한 자리(겹세로줄 옆 등)도 있어서
            # 아래 지운 그림 검사만으로는 못 막는다(실측 day2sb-1 단6 끝 마디).
            if any(y0 <= yi <= y1 for y0, y1 in lines or ()):
                continue
            # **오선을 지운 그림에 잉크가 없으면 점이 아니다.** 머리가 줄에
            # 걸치면 같은 높이 후보가 오선 위에 떨어져, 줄 잉크가 0.5 안팎의
            # "점"이 됐다(실측 day2sb-1: 모든 음의 점수가 0.44~0.58 로 비슷했던
            # 이유 — 줄 위 4분음표가 0.538 로 점4분이 됐다). 진짜 점은 줄을
            # 지워도 남는다.
            if ns is not None and not ns[max(0, yi - int(r)):yi + int(r) + 1,
                                         max(0, xi - int(r)):xi + int(r) + 1].any():
                continue
            core = g[yi - int(r):yi + int(r) + 1, xi - int(r):xi + int(r) + 1]
            out = g[yi - int(R):yi + int(R) + 1, xi - int(R):xi + int(R) + 1]
            if core.size == 0 or out.size == 0:
                continue
            paper = float(np.percentile(out, 75))
            span = max(1.0, paper - ink)                 # 종이 → 잉크 폭
            dark = (paper - float(core.mean())) / span
            ring = (float(out.mean()) - float(core.mean())) / span
            sc = min(dark, ring * 2.2)
            # **도돌이표의 점을 걸러 낸다.** `:‖` 는 점이 **세로로 두 개**고,
            # 음표 바로 뒤에 오면 붙임점 자리와 정확히 겹친다(실측: 위싱에서
            # 이렇게 생긴 가짜 붙임점 5개 — 도돌이표가 많은 콘티에서는
            # "점이 다 붙는" 것처럼 보인다). 붙임점은 하나뿐이므로,
            # 한 칸 위·아래에 같은 점이 또 있으면 붙임점이 아니다.
            if sc > 0 and _twin(g, xi, yi, r, R, span, spacing,
                                curves, head):
                continue
            if sc > best:
                best = sc
                best_run = (ink_run(ns, xi, yi, spacing)
                            if ns is not None else 0.0)
    return best, best_run


def _twin(g, xi: int, yi: int, r: float, R: float, span: float,
          spacing: float, curves=None, head=None) -> bool:
    """
    같은 x에서 한 칸쯤 위 또는 아래에 같은 점이 또 있는가 (도돌이표).

    간격을 정확히 한 칸으로 잡으면 놓친다 — 실측한 도돌이표 점 사이는
    0.93칸이었고 조판마다 다르다. 쌍의 문턱도 낮게 둔다: 굵은 마디선이
    옆에 있어 종이 기준이 어두워져 점수가 덜 나온다.

    **이음줄·붙임줄은 쌍으로 세지 않는다.** 음표 아래를 지나는 곡선이 딱
    그 자리를 지나가면 도돌이표로 오인해 진짜 붙임점을 통째로 버린다
    (실측 now0918-12 단2 마디2: 점수 0.717 짜리 선명한 점이 이것 때문에
    0.276 으로 떨어졌다). 주 위치에는 이미 같은 제외가 걸려 있다.
    """
    import numpy as np

    offs = [d * spacing for d in (-1.25, -1.1, -0.95, -0.8,
                                  0.8, 0.95, 1.1, 1.25)]
    for dy in offs:
        y2 = int(yi + dy)
        if not (R < y2 < g.shape[0] - R):
            continue
        if _on_curve(xi, y2, curves, spacing, head):
            continue
        core = g[y2 - int(r):y2 + int(r) + 1, xi - int(r):xi + int(r) + 1]
        out = g[y2 - int(R):y2 + int(R) + 1, xi - int(R):xi + int(R) + 1]
        if core.size == 0 or out.size == 0:
            continue
        paper = float(np.percentile(out, 75))
        dark = (paper - float(core.mean())) / span
        ring = (float(out.mean()) - float(core.mean())) / span
        if min(dark, ring * 2.2) < DOT_SCORE * 0.7:
            continue
        # **모양으로 점과 곡선을 가른다.** `_on_curve` 는 검출된 곡선 상자만
        # 보므로 못 잡는 이음줄이 있다. 붙임점은 지름이 0.4칸쯤인 작은 원이고
        # 이음줄은 가로로 길게 이어진다 — 옆으로 얼마나 번지는지 보면 갈린다.
        # (실측 now0918-12 단2 마디2: 음표 아래를 지나는 이음줄이 도돌이표의
        # 둘째 점으로 오인돼 0.717 짜리 진짜 붙임점이 통째로 버려졌다.)
        if _wide(g, xi, y2, r, paper, span, spacing):
            continue
        return True
    return False


def _wide(g, xi: int, yi: int, r: float, paper: float, span: float,
          spacing: float) -> bool:
    """이 자리의 잉크가 **붙임점보다 가로로 넓은가** (= 곡선·선이다)."""
    import numpy as np

    half = int(spacing * 0.75)
    lo, hi = max(0, xi - half), min(g.shape[1], xi + half + 1)
    row = g[max(0, yi - int(r)):yi + int(r) + 1, lo:hi]
    if row.size == 0:
        return False
    col = row.mean(axis=0)
    dark = (paper - col) / span >= DOT_SCORE * 0.5
    # 중심에서 좌우로 이어진 어두운 폭
    c = xi - lo
    if c >= len(dark) or not dark[c]:
        return False
    w = 1
    i = c - 1
    while i >= 0 and dark[i]:
        w += 1
        i -= 1
    i = c + 1
    while i < len(dark) and dark[i]:
        w += 1
        i += 1
    return w > spacing * 0.62      # 점 지름(약 0.4칸)보다 확실히 넓으면 선이다


def _dotted(head, dots, spacing: float) -> bool:
    """
    머리 오른쪽의 붙임점을 찾는다.

    점은 머리 바로 오른쪽 한 칸 안에, 머리와 같은 높이에 찍힌다. 머리가
    **줄 위**에 있으면 점은 줄에 겹치지 않게 반 칸 위로 올라가므로 세로
    허용치를 0.75칸으로 둔다.
    """
    hx = head["x"] + head["w"]
    hy = head["y"] + head["h"] / 2
    for d in dots:
        dx = d["x"] + d["w"] / 2 - hx
        if 0 <= dx <= spacing * 1.6 and \
           abs(d["y"] + d["h"] / 2 - hy) <= spacing * 0.75:
            return True
    return False


def fix_rest_class(boxes, staff_top: float, spacing: float) -> list[dict]:
    """
    온쉼표와 2분쉼표를 **자리로** 가른다.

    둘은 같은 짧은 막대라 검출기가 자주 뒤집는다(실측: 마커스 단0·단8에서
    온쉼표 하나가 2분쉼표 둘로, 단1에서는 그 반대). 2박씩 어긋나 마디 수를
    산술로 못 낸다.

    그런데 자리는 정해져 있다 — 둘 다 둘째·셋째 줄 사이 칸에 있고,
    온쉼표는 줄에 **매달려** 위 반쪽, 2분쉼표는 줄 **위에 앉아** 아래 반쪽이다.
    윗줄에서 잰 중심(칸 단위)이 온쉼표 1.29, 2분쉼표 1.76이었다(실측).
    1.5칸을 경계로 가르면 97.8%가 맞는다.
    """
    out = []
    for b in boxes:
        if b["class"] not in ("rest_whole", "rest_half"):
            out.append(b)
            continue
        pos = (b["y"] + b["h"] / 2 - staff_top) / spacing
        out.append({**b, "class": "rest_whole" if pos < 1.5 else "rest_half"})
    return out


# **속 빈 머리 보정은 넣었다가 뺐다.**
# 검출기가 빈 머리를 찬 머리로 부르면 4분음표가 되므로, 머리 속 밝기로
# 되돌리려 했다. 지표는 깔끔해 보였다 — 머리 3,088개에서 속 비움 중앙값이
# 8분 1 · 4분 1 · 2분 123 · 온음표 142 로 완전히 갈렸다.
#
# 그런데 A/B 103장에서 **깨진 마디 804 -> 826, 나빠진 마디 41개**였다.
# 맞던 마디를 깨뜨린다. 분포가 갈린다고 낱낱의 판정이 맞는 것은 아니다 —
# 흐린 스캔의 찬 머리도 가운데가 밝게 나온다. 되돌린다.
#
# (처음에는 클래스 이름을 notehead_black 으로 써서 조건이 영원히 거짓이었고,
#  변화 0 을 "지표가 못 보는 개선"으로 착각할 뻔했다. 실제 이름은
#  notehead_filled 다. 변화가 0 이면 먼저 코드가 도는지부터 확인한다.)

def ink_run(ns, xi: int, yi: int, spacing: float) -> float:
    """
    **오선을 지운 그림**에서 (xi, yi) 를 지나는 가로 잉크의 폭 (칸 단위).

    붙임점을 선과 가르는 **증거로 기록만 한다.** 원본 회색 그림에서 재면
    오선 줄이 같은 띠에 들어와 172개 중 131개가 창 끝까지 이어졌지만,
    오선을 지우면 갈린다 — 진짜 붙임점 0.4~0.5칸, 이음줄·빔 1.4칸 이상
    (7장 실측: 점으로 인정된 65개 중 10개가 2.1~4.1칸이었다).

    **그런데 이걸로 거부하게 했더니 더 나빠졌다** — 깨진 마디 24 → 25.
    폭이 0.0 으로 나오는 자리가 섞여 있어서다(오선과 함께 지워진 진짜 점).
    판정은 박자(`demote_dots`)에 맡기고, 여기서는 재서 남기기만 한다.
    """
    import numpy as np
    half = int(spacing * 2.0)
    lo, hi = max(0, xi - half), min(ns.shape[1], xi + half + 1)
    band = ns[max(0, yi - 1):yi + 2, lo:hi]
    if band.size == 0:
        return 0.0
    on = band.any(axis=0)
    c = xi - lo
    if c >= len(on) or not on[c]:
        return 0.0
    w = 1
    i = c - 1
    while i >= 0 and on[i]:
        w += 1; i -= 1
    i = c + 1
    while i < len(on) and on[i]:
        w += 1; i += 1
    return w / spacing


def _blob(ns, xi: int, yi: int, spacing: float, lim: float = 0.8):
    """
    (xi, yi) 에서 이어진 잉크 덩어리의 상자 (x0, y0, x1, y1) — 가로·세로
    어느 쪽이든 `lim` 칸 이상이면 None.

    **한 화소를 지나는 가로·세로 길이로는 모양을 못 잰다.** 사선은 어느
    화소에서 재도 1px 이라 "작은 점"으로 통과했다(Codex 리뷰 재현: 가로
    120px 사선이 0.78). 덩어리 전체를 따라가야 크기가 나온다.
    """
    import numpy as np
    r = int(spacing * lim) + 2                    # 이 창을 벗어나면 이미 크다
    H, W = ns.shape
    wx0, wy0 = max(0, xi - r), max(0, yi - r)
    wx1, wy1 = min(W, xi + r + 1), min(H, yi + r + 1)
    win = ns[wy0:wy1, wx0:wx1]
    seen = np.zeros_like(win, dtype=bool)
    sy, sx = yi - wy0, xi - wx0
    if not win[sy, sx]:
        return None
    stack, seen[sy, sx] = [(sy, sx)], True
    ys, xs = [sy], [sx]
    h, w = win.shape
    while stack:
        y, x = stack.pop()
        if y in (0, h - 1) or x in (0, w - 1):
            return None                           # 창 끝까지 이어진다 = 크다
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                y2, x2 = y + dy, x + dx
                if win[y2, x2] and not seen[y2, x2]:
                    seen[y2, x2] = True
                    stack.append((y2, x2))
                    ys.append(y2); xs.append(x2)
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    if (x1 - x0 + 1) >= lim * spacing or (y1 - y0 + 1) >= lim * spacing:
        return None
    return (wx0 + x0, wy0 + y0, wx0 + x1, wy0 + y1)


def rest_dot_score(ns, box, spacing: float, rgb=None, lines=None) -> float:
    """
    쉼표 오른쪽 붙임점 자리에 **점 모양** 잉크가 있나 (0~1).

    왜 머리와 다른 함수인가(실측):
      · 자리가 다르다. 쉼표의 점은 쉼표가 걸친 줄의 **한 칸 위**에 온다 —
        머리처럼 중심 높이가 아니다.
      · 원본 회색으로 재면 **거꾸로 나온다.** 온·2분쉼표는 오선 줄에
        붙어 있어서, 점 없는 쉼표가 0.55 로 높고 진짜 점 붙은 쉼표가
        0.25 로 낮았다(5장 실측). 줄이 점수를 먹는다.
      · **오선을 지운 그림**에서 재면 갈린다 — 점 없는 쉼표 47개가 전부
        0.00 이고, 점이 보이는 것은 모두 0.11 이상이었다.

    모양도 본다 — 붙임점은 지름 0.4칸쯤인 작은 점이고, 막대선·기둥은
    세로로 길다. 가로·세로 둘 다 0.8칸 미만일 때만 센다.

    점수만으로는 완전히 갈리지 않는다(0 초과 21개 중 진짜가 7개).
    **판정은 박자가 한다** — `promote_dots` 가 합이 모자란 마디에서만,
    점수가 가장 높은 후보를 쓴다.
    """
    import numpy as np
    if ns is None:
        return 0.0
    cx = box["x"] + box["w"]
    cy = box["y"] + box["h"] / 2.0
    hit = tot = 0
    # **같은 높이·바짝 붙은 자리도 본다.** 2분쉼표는 몸통이 줄 위 칸에
    # 있어서 점이 몸통과 같은 높이로 0.2~0.5칸 옆에 붙기도 한다(실측
    # wish0823-3 끝 마디 𝄼.: 옛 자리 9곳이 전부 비어 0.00 → fit_page 가
    # 8분 둘을 4분으로 늘려 맞췄다). 큰 덩어리는 _blob 이, 엉뚱한 승격은
    # 박자가 막는다.
    # **쉼표 자신을 지운 조각에서 잰다.** 점이 몸통에 바짝 붙으면 둘이
    # 한 덩어리가 되어 "너무 크다"로 빠졌다(실측 wish0823-3 𝄼.).
    # 몸통은 제 점일 수 없으니 지워도 잃는 증거가 없다.
    ox = max(0, int(box["x"]) - 2)
    oy = max(0, int(cy - 2 * spacing))
    loc = ns[oy:min(ns.shape[0], int(cy + 2 * spacing)),
             ox:min(ns.shape[1], int(cx + 2 * spacing))].copy()
    loc[max(0, int(box["y"]) - 1 - oy):int(box["y"] + box["h"]) + 2 - oy,
        max(0, int(box["x"]) - 1 - ox):int(cx) + 2 - ox] = False
    # **오선도 여기서 지운다.** 오선 제거는 머리를 지키느라 기호가 걸친
    # 줄을 남기는데, 2분쉼표는 줄 위에 앉고 점은 그 줄에 닿는다 — 점과
    # 줄이 한 덩어리가 되어 "너무 크다"로 빠졌다(실측 day2sb-1 단6 마디6
    # 𝄼. 가 0.00). `lines` 는 그 단의 줄 (위, 아래) 화소 범위.
    for y0, y1 in lines or ():
        loc[max(0, int(y0) - 1 - oy):max(0, int(y1) + 2 - oy), :] = False
    for dy in (-0.9, -0.7, -0.5, -0.25, 0.0):
        for ddx in (0.3, 0.5, 0.8, 1.1):
            xi = int(cx + spacing * ddx) - ox
            yi = int(cy + spacing * dy) - oy
            if not (2 < xi < loc.shape[1] - 2 and 2 < yi < loc.shape[0] - 2):
                continue
            tot += 1
            win = loc[yi - 2:yi + 3, xi - 2:xi + 3]
            if not win.any():
                continue
            # **모양은 잉크 화소에서 재야 한다.** 창 안에 잉크가 있다고
            # 가운데 화소에 있는 건 아니다 — 가운데에서 재면 창을 스치는
            # 빔·막대선이 "짧다"고 나와 점으로 통과한다.
            dyi, dxi = [int(v[0]) for v in np.nonzero(win)]
            yk, xk = yi - 2 + dyi, xi - 2 + dxi
            # 붙임점은 지름 0.4칸쯤의 둥근 점이다. 넓힌 자리에서는 다음 음표
            # 머리 가장자리·작은 글자도 걸리므로(Codex 재현: 0.67×0.44칸
            # 타원이 0.30) 0.6칸 미만·가로세로 2배 안쪽만 센다.
            blob = _blob(loc, xk, yk, spacing, lim=0.6)
            if blob is None:
                continue
            bw, bh = blob[2] - blob[0] + 1, blob[3] - blob[1] + 1
            if max(bw, bh) > 2 * min(bw, bh):
                continue
            # **손으로 적은 표시는 점이 아니다.** 콘티는 빨간 펜으로
            # 고쳐 쓰므로, 쉼표 옆 빨간 획이 붙임점으로 들어가면 그
            # 마디가 맞아 보이면서 틀린다(실측 wish0809-3 단2 마디1).
            # 머리·쉼표 검출에 이미 쓰는 판정과 같은 것을 쓴다.
            if rgb is not None:
                from evaldet import colored
                # **표시 전체를 잰다.** 첫 화소 둘레 7×7 만 보면 나머지
                # 빨간 잉크가 "주변"으로 들어가 색 차이가 사라진다.
                bx0, by0, bx1, by1 = blob
                if colored(rgb, bx0 + ox - 1, by0 + oy - 1,
                           bx1 - bx0 + 3, by1 - by0 + 3):
                    continue
            hit += 1
    return hit / max(1, tot)


def hollow_score(head, g) -> float | None:
    """
    머리 **가운데가 얼마나 비었나** (0 = 꽉 참, 1 = 테두리만 있고 속은 종이).

    **잴 수 없으면 None 이다 — 0 이 아니다.** 0 은 "꽉 찼다"는 증거라
    `demote_hollow` 가 그 머리를 2분 → 4분으로 깎는다. × 머리·너무 작은
    상자를 0 으로 돌려주면 멀쩡한 2분음표가 깎이고, 합이 맞으니 짐작
    표시도 안 남아 그대로 과금된다(Codex 리뷰 재현).

    2분·온음표는 속이 비어 있고 4분 이하는 꽉 찼다. 검출기가 그 둘을
    헷갈리면 음가가 통째로 틀리는데(2분 → 4분이면 한 마디가 1박 모자라다),
    **화소로는 분명히 갈린다** — 가운데 밝기와 테두리 밝기의 차이다.

    절대 밝기로 재면 인쇄 농도·해상도에 흔들리므로, 머리 자신의 가장 진한
    잉크와 그 둘레 종이를 기준자로 쓴다(붙임점 점수와 같은 방식).
    """
    import numpy as np
    x0, y0 = int(head["x"]), int(head["y"])
    x1, y1 = int(head["x"] + head["w"]), int(head["y"] + head["h"])
    box = g[max(0, y0):y1 + 1, max(0, x0):x1 + 1]
    if box.size == 0 or box.shape[0] < 4 or box.shape[1] < 4:
        return None
    ih = max(1, box.shape[0] // 4)
    iw = max(1, box.shape[1] // 4)
    core = box[ih:box.shape[0] - ih, iw:box.shape[1] - iw]
    if core.size == 0:
        return None
    ink = float(np.percentile(box, 10))           # 테두리의 진한 잉크
    paper = float(np.percentile(box, 95))         # 상자 안의 밝은 쪽
    if paper - ink < SOLID_SPAN:
        # 상자가 한 색이다. 진하면 통째로 잉크(꽉 찬 머리), 밝으면 잴 게 없다.
        # 한 색일 때만 절대 밝기를 본다 — 기준자를 세울 대비가 없으니까.
        return 0.0 if float(np.median(box)) < 128 else None
    span = paper - ink
    # **× 머리를 뺀다.** 낭송·랩 파트는 머리가 ×인데 가운데가 비어 있어
    # 속 비움이 0.21~0.36 으로 나온다 — 2분음표로 읽히면 그 마디가 길어진다
    # (실측: 속 비움으로 올린 머리 8개 중 7개가 × 였다).
    # 가르는 것은 **테두리 좌우**다. 속 빈 머리는 양옆이 굵은 잉크고,
    # × 는 팔이 모서리로 가서 양옆 가운데가 비어 있다
    # (실측: × 24개가 전부 0.2 이하, 진짜 속 빈 머리는 0.3~0.9).
    mid = box.shape[0] // 2
    wedge = max(1, box.shape[1] // 6)
    side = max(float(box[max(0, mid - 1):mid + 2, :wedge].mean()),
               float(box[max(0, mid - 1):mid + 2, -wedge:].mean()))
    score = max(0.0, min(1.0, (float(np.median(core)) - ink) / span))
    # × 검사는 **가운데가 밝을 때만** 한다. 가운데가 진하면 × 일 수 없다.
    # 꽉 찬 머리도 상자에 여백이 있으면 양옆이 종이라 이 검사에 걸렸다
    # (실측 wish0823-3: 꽉 찬 머리 107개 중 33개가 None).
    if score >= DARK_CORE and (paper - side) / span < SIDE_INK_MIN:
        return None
    # **가운데가 진해도 밝은 구멍이 있으면 꽉 찬 게 아니다.** 비스듬하고
    # 좁은 구멍의 2분음표는 중앙값이 검정이라 0 이 나오고, 0 은
    # demote_hollow 에 "확실히 꽉 참"이다(Codex 재현: 정상 2분이 4분으로).
    if score < DARK_CORE and float((core > ink + 0.5 * span).mean()) >= HOLE_MIN:
        return None
    return score


def _cover(a, b, k0: str, k1: str) -> float:
    """두 상자가 한 축에서 겹친 길이 / 짧은 쪽 길이."""
    lo, hi = max(a[k0], b[k0]), min(a[k0] + a[k1], b[k0] + b[k1])
    return max(0.0, hi - lo) / max(1e-6, min(a[k1], b[k1]))


def _drop_twin_beams(marks: list[dict], spacing: float) -> list[dict]:
    """
    **같은 획에 1차·2차 빔 이름이 둘 다 붙으면 확신이 높은 쪽만 남긴다.**

    진짜 겹빔은 2차 빔이 0.75칸 떨어진 다른 획이라 상자가 이렇게 포개지지
    않는다. 실측 day2conti-2 단1: beam1(0.47) 과 거의 같은 상자의
    beam2(0.38) 때문에 점8분이 16분으로 읽혔고, 합을 맞추느라 점이 엉뚱한
    음에 붙어 틀린 채 과금됐다. 105장에서 포개진 쌍 15개 중 진짜 겹빔
    (#now0918-10 등)은 2차 쪽 확신이 0.90 으로 높아 그대로 남는다.
    """
    b1 = [m for m in marks if m["class"] == "beam1"]
    drop = set()
    for m in marks:
        if m["class"] != "beam2":
            continue
        for a in b1:
            # **높이가 거의 같아야 한다.** 비스듬한 진짜 겹빔은 0.75칸
            # 떨어져 있어도 축 정렬 상자는 세로로 60% 넘게 겹친다(Codex 재현).
            if (_cover(a, m, "x", "w") > 0.8
                    and abs(_cy(a) - _cy(m)) < spacing * 0.25
                    and m.get("conf", 0.0) < a.get("conf", 0.0)):
                drop.add(id(m))
                break
    return [m for m in marks if id(m) not in drop]


def read_durations(boxes, spacing: float, gray=None,
                   mask_extra=None, nostaff=None, lines=None) -> list[dict]:
    """
    한 단의 검출 상자에서 음표마다 음가를 정한다.

    빈 머리는 그 자체로 음가가 정해진다(2분·온음표는 빔이 없다).
    꽉 찬 머리만 빔·꼬리를 세어 4분/8분/16분을 가른다.
    gray를 주면 붙임점을 화소로도 확인한다 — 검출기만으로는 못 잡는다.
    mask_extra 는 가려야 할 다른 상자(곡선 등). 다른 모델이 낸 것도 받는다.
    반환: x 순서로 [{x, y, w, h, duration, level, dotted}]
    """
    heads = sorted((b for b in boxes if b["class"].startswith("notehead")),
                   key=lambda b: b["x"])
    marks = _drop_twin_beams([b for b in boxes
                              if b["class"] in BEAM_LEVEL or b["class"] in FLAG_LEVEL],
                             spacing)
    dots = [b for b in boxes if b["class"] == "aug_dot"]
    runs = beam_runs(marks, spacing)
    g = occ = None
    if gray is not None:
        import numpy as np
        g = gray if hasattr(gray, "shape") else \
            np.asarray(gray.convert("L")).astype("float32")
        occ = _occupancy(boxes, g.shape, spacing)
    # 가림막에서 뺀 곡선은 획 판정(_on_curve)으로 넘긴다
    curves = list(mask_extra or []) + [b for b in boxes if b["class"] in CURVE]
    ns = None
    if nostaff is not None:
        import numpy as np
        ns = (nostaff if hasattr(nostaff, "shape")
              else np.asarray(nostaff))
    out = []
    for h in heads:
        beam = -1
        cls = h["class"]
        if cls == "notehead_whole":
            dur, lv = "whole", 0
        elif cls == "notehead_half":
            dur, lv = "half", 0
        else:
            lv, beam = _level_and_beam(h, marks, spacing, runs)
            dur = LEVEL_DUR[lv]
        dot = _dotted(h, dots, spacing)
        sc, run = (1.0, 0.0) if dot else (0.0, 0.0)
        if not dot and g is not None:
            sc, run = _dot_score(h, g, occ, spacing, curves, ns, lines)
            dot = sc >= DOT_SCORE
        hol = hollow_score(h, g) if g is not None else None
        out.append({**h, "duration": dur, "level": lv, "beamGroup": beam,
                    "dotted": dot, "dotScore": round(sc, 3),
                    "dotRun": round(run, 3), "hollow": None if hol is None else round(hol, 3)})
    return out
