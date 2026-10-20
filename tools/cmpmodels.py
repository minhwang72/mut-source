#!/usr/bin/env python3
"""
구조 판독을 **모델별로 재서 비용 대비 정확도**를 낸다.

왜 필요한가: 구조 판독이 변환 비용의 거의 전부다(실측: 악보 한 장에 $3~4.5,
그중 코드 판독은 20원 수준이고 나머지가 구조 판독이다). 단별로 부르므로
호출이 9~11회고 출력이 4~5천 토큰씩 나온다. 모델을 한 단계 낮출 수 있으면
비용이 5~30배 줄어든다.

판정 기준은 **박자 검산**이다 — 정답 악보가 없어도 4/4박이면 마디마다 음가
합이 맞아야 한다. 마디 수·음표 수는 검증된 Opus 판과 비교한다.

  python tools/cmpmodels.py <악보> --base <opus.struct.json> -o <폴더>
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 1M 토큰당 달러 (입력, 출력)
PRICE = {
    "claude-opus-5": (15.0, 75.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
}


def score(struct: dict) -> dict:
    """박자 검산 결과와 규모."""
    import checkbeats as CB

    r = CB.check(struct)
    sysv = struct["systems"]
    return {
        "systems": len(sysv),
        "measures": sum(s.get("measures", 0) for s in sysv),
        "notes": sum(1 for s in sysv for n in s.get("notes", [])
                     if not n.get("rest")),
        "rests": sum(1 for s in sysv for n in s.get("notes", [])
                     if n.get("rest")),
        "beatOk": r["ok"],
        "beatChecked": r["checked"],
        "bad": len(r["over"]) + len(r["under"]),
        "failed": sum(1 for s in sysv if not s.get("notes")),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="구조 판독 모델 비교")
    ap.add_argument("image")
    ap.add_argument("--base", required=True, help="기준 struct.json (Opus)")
    ap.add_argument("-o", "--out", required=True, help="결과를 둘 폴더")
    ap.add_argument("--models", default="claude-sonnet-5,"
                                        "claude-haiku-4-5-20251001")
    a = ap.parse_args()

    from PIL import Image

    import readstruct as RS

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    img = Image.open(a.image)
    name = Path(a.image).stem

    base = json.loads(Path(a.base).read_text(encoding="utf-8"))
    b = score(base)
    bt = base.get("tokens", {})
    pi, po = PRICE["claude-opus-5"]
    bcost = bt.get("in", 0) / 1e6 * pi + bt.get("out", 0) / 1e6 * po
    print(f"{name}")
    print(f"  기준(Opus): 단 {b['systems']} · 마디 {b['measures']} · "
          f"음표 {b['notes']} · 박자 {b['beatOk']}/{b['beatChecked']} · "
          f"${bcost:.2f}")

    for model in a.models.split(","):
        f = out / f"{name}.{model.split('-')[1]}.struct.json"
        t0 = time.time()
        try:
            data = RS.read_page(img, model)
        except Exception as e:                       # noqa: BLE001
            print(f"  {model}: 실패 — {str(e)[:80]}")
            continue
        f.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                     encoding="utf-8")
        s = score(data)
        tk = data.get("tokens", {})
        pi, po = PRICE.get(model, (0, 0))
        cost = tk.get("in", 0) / 1e6 * pi + tk.get("out", 0) / 1e6 * po
        dm = s["measures"] - b["measures"]
        dn = s["notes"] - b["notes"]
        print(f"  {model.split('-')[1]:8s}: 단 {s['systems']} · "
              f"마디 {s['measures']}({dm:+d}) · 음표 {s['notes']}({dn:+d}) · "
              f"박자 {s['beatOk']}/{s['beatChecked']} · "
              f"실패단 {s['failed']} · ${cost:.3f} · {time.time()-t0:.0f}초"
              f"  ({bcost / cost:.0f}배 쌈)" if cost else "")


if __name__ == "__main__":
    main()
