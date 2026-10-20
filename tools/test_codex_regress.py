"""리뷰에서 재현한 네 결함의 회귀 검사 — 악보 없이 합성 배열만 쓴다.

    python tools/test_codex_regress.py

현재 구현의 실패도 모두 볼 수 있게 끝까지 실행한 뒤 실패 시 1로 종료한다.
"""
import ast
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np                                            # noqa: E402
from durations import hollow_score, rest_dot_score             # noqa: E402
from fitdur import demote_hollow                               # noqa: E402

SP = 18.0
REST = {"x": 60.0, "y": 92.0, "w": 18.0, "h": 9.0}


def blank():
    return np.zeros((200, 200), dtype=bool)


def test_x_head_has_unknown_hollowness():
    box = {"x": 10, "y": 10, "w": 24, "h": 20}
    gray = np.full((60, 60), 255.0, dtype="float32")
    for t in range(20):
        gray[10 + t, 10 + int(t * 24 / 20)] = 20.0
        gray[10 + t, 33 - int(t * 24 / 20)] = 20.0
    score = hollow_score(box, gray)
    assert score is None, f"× 가드의 판정 불가는 None이어야 함: {score!r}"


def test_small_head_has_unknown_hollowness():
    gray = np.full((40, 40), 255.0, dtype="float32")
    # 함수가 양 끝을 포함해 자르므로 w/h=2이면 실제 표본은 3px다.
    for w, h in ((2, 16), (20, 2)):
        box = {"x": 10, "y": 10, "w": w, "h": h}
        score = hollow_score(box, gray)
        assert score is None, f"4px 미만 상자({w=}, {h=})는 None이어야 함: {score!r}"


def test_unknown_half_is_not_demoted():
    # half + half + quarter = 5박. 첫 half는 판정 불가, 둘째는 확실히 비었다.
    notes = [{"duration": d, "dotted": False, "hollow": hollow}
             for d, hollow in (("half", None), ("half", 0.7), ("quarter", 0.0))]
    measure = {"notes": notes, "rest": 0.0, "items": list(notes)}
    changed = demote_hollow([[measure]], beats=4.0)
    assert changed == 0, f"판정 불가 음표를 내리면 안 됨: {changed=}"
    assert [n["duration"] for n in notes] == ["half", "half", "quarter"]
    assert not any(n.get("hollowDemoted") for n in notes)


def test_long_diagonal_is_not_a_rest_dot():
    ns = blank()
    # 가로 120px, 8방향으로 연결된 사선이 점 탐색 위치 (92, 83)를 지난다.
    # 가로·세로 한 줄만 재면 각 방향 길이가 1px여서 작은 점으로 오인한다.
    xs = np.arange(30, 150)
    ns[xs - 9, xs] = True
    score = rest_dot_score(ns, REST, SP)
    assert score == 0.0, f"120px 연결 사선을 붙임점으로 오인함: {score=}"


def test_real_round_rest_dot_is_kept():
    yy, xx = np.ogrid[:200, :200]
    # 중심 (92, 83), 반지름 3: 양 끝 화소를 포함한 지름은 7px다.
    ns = (xx - 92) ** 2 + (yy - 83) ** 2 <= 3 ** 2
    score = rest_dot_score(ns, REST, SP)
    assert score > 0.0, f"진짜 7px 원형 붙임점은 유지해야 함: {score=}"


def test_red_rest_mark_is_rejected_at_its_edge():
    ns = blank()
    ns[80:87, 89:96] = True
    rgb = np.full((*ns.shape, 3), 255, dtype="uint8")
    rgb[ns] = (200, 20, 20)
    # 탐색창에서 처음 잡는 잉크가 표시 가장자리다. 그 주변 7x7에는
    # 빨강 일부가 남아 색 판정의 배경으로 섞이지만 표시 전체는 빨강이다.
    assert rest_dot_score(ns, REST, SP) > 0.0  # 색 필터 없이는 점 후보
    score = rest_dot_score(ns, REST, SP, rgb=rgb)
    assert score == 0.0, f"빨간 7x7 표시의 가장자리를 붙임점으로 오인함: {score=}"


def test_local_reader_passes_rgb_to_build_from():
    path = Path(__file__).resolve().parents[1] / "server" / "local_reader.py"
    # 서버를 import하거나 실행하지 않고 실제 호출의 키워드만 검사한다.
    tree = ast.parse(path.read_text(encoding="utf-8"))
    calls = [node for node in ast.walk(tree)
             if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute)
             and isinstance(node.func.value, ast.Name)
             and node.func.value.id == "DS" and node.func.attr == "build_from"]
    assert calls, "local_reader.py에 DS.build_from 호출이 없음"
    for call in calls:
        assert any(kw.arg == "rgb" for kw in call.keywords), (
            f"local_reader.py:{call.lineno} DS.build_from 호출에 rgb= 인자가 없음")


def test_split_measure_is_not_reused_as_a_pickup():
    from fitdur import pickup_pair, promote_hollow

    # [[1박], [3박, 4박, 3박]]: 첫 1박은 다음 단의 3박과 이미 짝이다.
    systems = []
    for counts in ((1,), (3, 4, 3)):
        measures = []
        for count in counts:
            notes = [{"duration": "quarter", "dotted": False, "hollow": 0.0}
                     for _ in range(count)]
            measures.append({"notes": notes, "rest": 0.0, "items": list(notes)})
        systems.append(measures)
    last = systems[-1][-1]["notes"]
    last[0]["hollow"] = 0.7
    assert pickup_pair(systems, beats=4.0) == set(), "줄바꿈 짝을 못갖춘마디로 재사용함"
    changed = promote_hollow(systems, beats=4.0)
    assert changed == 1, f"끝 마디가 잠겨 빈 머리를 복구하지 못함: {changed=}"
    assert [n["duration"] for n in last] == ["half", "quarter", "quarter"]
    assert last[0].get("hollowPromoted")
    assert all(n["duration"] == "quarter"
               for m in (systems[0][0], *systems[1][:-1]) for n in m["notes"])


def test_large_or_elongated_blob_is_not_a_rest_dot():
    yy, xx = np.ogrid[:200, :200]
    # (6, 4)는 지름 13×9px로 0.6칸을 넘는다. (4, 1)은 9×3px로
    # 크기는 작지만 가로세로 비가 2배를 넘으므로 별도로 거부해야 한다.
    for rx, ry in ((6, 4), (4, 1)):
        ns = ((xx - 92) / rx) ** 2 + ((yy - 83) / ry) ** 2 <= 1
        score = rest_dot_score(ns, REST, SP)
        assert score == 0.0, f"타원 덩어리를 붙임점으로 오인함: {rx=}, {ry=}, {score=}"


def test_single_hit_rest_dot_promotes_only_the_half_rest():
    from fitdur import promote_dots

    yy, xx = np.ogrid[:200, :200]
    # 오른쪽 끝 탐색 자리 한 곳만 잡히는 반지름 1의 실제 원형 점.
    ns = (xx - 98) ** 2 + (yy - 96) ** 2 <= 1
    score = rest_dot_score(ns, REST, SP)
    assert score == 0.05, f"20곳 중 한 곳에서 점을 잡아야 함: {score=}"
    rest = {"duration": "half", "dotted": False, "rest": True, "dotScore": score}
    notes = [{"duration": "eighth", "dotted": False} for _ in range(2)]
    before = [dict(n) for n in notes]
    measure = {"notes": notes, "rest": 2.0, "items": [rest, *notes]}
    changed = promote_dots([[measure]], beats=4.0)
    assert changed == 1, f"한 곳에서 잡힌 실제 쉼표 점을 놓침: {changed=}"
    assert rest["duration"] == "half" and rest["dotted"] and rest.get("dotPromoted")
    assert measure["rest"] == 3.0, "점2분쉼표의 박자 합이 갱신되지 않음"
    assert notes == before, "쉼표에 점을 붙이면서 8분음표 둘을 바꿈"


def test_narrow_hole_has_unknown_hollowness():
    box = {"x": 10, "y": 10, "w": 24, "h": 16}
    yy, xx = np.ogrid[:40, :50]
    gray = np.full((40, 50), 255.0, dtype="float32")
    outer = ((xx - 22) / 12) ** 2 + ((yy - 18) / 8) ** 2 <= 1
    hole = ((xx - 22) / 7) ** 2 + ((yy - 18) / 1.5) ** 2 <= 1
    gray[outer & ~hole] = 20.0
    # 가로로 좁게 열린 구멍은 있지만 가운데 영역의 중앙값은 여전히 잉크다.
    # 0.0을 주면 확실히 찬 머리라는 잘못된 증거로 쓰인다.
    score = hollow_score(box, gray)
    assert score is None, f"좁은 구멍이 있는 빈 머리는 판정 불가여야 함: {score!r}"


if __name__ == "__main__":
    tests = (
        test_x_head_has_unknown_hollowness,
        test_small_head_has_unknown_hollowness,
        test_unknown_half_is_not_demoted,
        test_long_diagonal_is_not_a_rest_dot,
        test_real_round_rest_dot_is_kept,
        test_red_rest_mark_is_rejected_at_its_edge,
        test_local_reader_passes_rgb_to_build_from,
        test_split_measure_is_not_reused_as_a_pickup,
        test_large_or_elongated_blob_is_not_a_rest_dot,
        test_single_hit_rest_dot_promotes_only_the_half_rest,
        test_narrow_hole_has_unknown_hollowness,
    )
    failed = 0
    for test in tests:
        try:
            test()
        except Exception as exc:
            failed += 1
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
        else:
            print(f"PASS {test.__name__}")
    print(f"{len(tests) - failed} passed, {failed} failed")
    if failed:
        raise SystemExit(1)
    print("ok")
