#!/usr/bin/env python3
"""
합성 데이터로 악보 기호 검출기를 학습한다.

왜 학습으로 가나: 손으로 맞춘 문턱값은 **조판을 넘으면 무너진다.** 실측으로
마커스 악보(머리 폭 2.21칸)에서 단당 7~18개를 잡던 검출기가 위싱 콘티
(1.39칸)에서 0~1개로 전멸했다. 두 악보를 동시에 만족하는 고정 문턱은
찾지 못했다. 자세한 경위는 README "막힌 지점" 참고.

데이터는 tools/gendata.py 가 만든다 — Verovio로 그리면 기호 위치와 종류를
이미 알고 있으므로 라벨링 노동이 0이고 원하는 만큼 만들 수 있다.

    python3 tools/train.py --data data/synth --epochs 60

학습이 끝나면 ONNX로 내보낸다. 배포는 브라우저에서 ONNX Runtime Web으로
돌리므로 **이미지가 서버로 나가지 않는다** — 저작권 방어선을 지킨다.
"""

from __future__ import annotations

import argparse
import os
import random
import shutil
from pathlib import Path


def split(src: Path, out: Path, val_ratio: float = 0.12, seed: int = 0) -> Path:
    """gendata 결과를 YOLO가 기대하는 train/val 구조로 나눈다."""
    names = sorted(p.stem for p in (src / "images").glob("*.png"))
    rng = random.Random(seed)
    rng.shuffle(names)
    cut = max(1, int(len(names) * val_ratio))
    parts = {"val": names[:cut], "train": names[cut:]}

    # **복사하지 않고 하드링크한다.** 6000장이면 1GB 가까이 되는데, 분할본을
    # 새로 만들 때마다 그만큼 또 쓴다. 디스크가 빠듯한 서버(실측 학습 서버: 여유
    # 19G/92% 사용)에서는 이 복사만으로 I/O 가 포화돼 sshd 가 응답을 못 할
    # 정도로 밀렸다. 같은 파일시스템이면 하드링크는 공간도 시간도 0 이다.
    linked = copied = 0
    for part, items in parts.items():
        for kind, ext in (("images", ".png"), ("labels", ".txt")):
            d = out / kind / part
            d.mkdir(parents=True, exist_ok=True)
            for n in items:
                s = src / kind / (n + ext)
                if not s.exists():
                    continue
                dst = d / (n + ext)
                if dst.exists():
                    continue                      # 이미 만든 분할본은 그대로 쓴다
                try:
                    os.link(s, dst); linked += 1
                except OSError:                   # 파일시스템이 다르면 복사
                    shutil.copy2(s, dst); copied += 1

    classes = (src / "classes.txt").read_text().split()
    yaml = [f"path: {out.resolve()}", "train: images/train", "val: images/val",
            f"nc: {len(classes)}", "names:"]
    yaml += [f"  {i}: {c}" for i, c in enumerate(classes)]
    (out / "data.yaml").write_text("\n".join(yaml) + "\n")
    print(f"학습 {len(parts['train'])}장 · 검증 {len(parts['val'])}장 "
          f"· 클래스 {len(classes)}종 (하드링크 {linked} · 복사 {copied})")
    return out / "data.yaml"


def main() -> None:
    ap = argparse.ArgumentParser(description="악보 기호 검출기 학습")
    ap.add_argument("--data", default="data/synth", help="gendata 출력 폴더")
    ap.add_argument("--work", default="data/yolo", help="분할본을 놓을 폴더")
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--imgsz", type=int, default=960,
                    help="악보는 가로로 길고 기호가 작다. 640은 부족하다")
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--mosaic", type=float, default=0.3,
                    help="모자이크 증강. 큰 imgsz 에서는 4장을 이어 붙인 "
                         "두 배 캔버스를 만들어 메모리를 크게 먹는다 — "
                         "메모리가 빠듯하면 0 으로 끈다")
    ap.add_argument("--workers", type=int, default=2,
                    help="데이터로더 프로세스 수. ultralytics 기본 8은 공용 "
                         "서버에서 다른 컨테이너를 굶긴다")
    ap.add_argument("--model", default="yolo11n.pt")
    ap.add_argument("--device", default=None,
                    help="cuda면 0, 애플 실리콘이면 mps, CPU면 cpu")
    ap.add_argument("--split-only", action="store_true")
    ap.add_argument("--project", default="runs")
    ap.add_argument("--name", default="omr")
    # ultralytics는 에폭마다 last.pt를 저장한다. 중단됐거나(잠자기·전원)
    # 일부러 멈춘 뒤 이어서 돌릴 때 쓴다 — 처음부터 다시 하지 않는다.
    ap.add_argument("--lr0", type=float, default=None,
                    help="이어 학습(warm start)이면 낮춰 준다 (예: 0.003)")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--ckpt", help="이어받을 last.pt 경로를 직접 지정")
    a = ap.parse_args()

    yaml = split(Path(a.data), Path(a.work))
    if a.split_only:
        return

    from ultralytics import YOLO

    if a.resume:
        ckpt = Path(a.ckpt) if a.ckpt else None
        if ckpt is None:
            # ultralytics가 task 폴더를 한 겹 더 만들어(runs/detect/runs/full)
            # 경로가 어긋난다. **실행 이름으로 한정해서** 찾는다 — 전체를
            # 훑으면 이름이 다른 옛 실행을 집는다(실측: runs/detect/train을
            # 집어서 4/100 에폭짜리 엉뚱한 학습이 이어졌다).
            found = sorted(Path(a.project).rglob(f"{a.name}/weights/last.pt"))
            if not found:
                raise SystemExit(
                    f"'{a.name}' 실행의 체크포인트(last.pt)를 못 찾았습니다.")
            ckpt = found[-1]
        if not ckpt.exists():
            raise SystemExit(f"체크포인트가 없습니다: {ckpt}")
        done = 0
        csv = ckpt.parent.parent / "results.csv"
        if csv.exists():
            done = max(0, len(csv.read_text().strip().split("\n")) - 1)
        print(f"이어서 학습: {ckpt}  (저장된 에폭 {done})")
        YOLO(str(ckpt)).train(resume=True)
        return

    model = YOLO(a.model)
    extra = {"lr0": a.lr0} if a.lr0 else {}
    model.train(data=str(yaml), epochs=a.epochs, imgsz=a.imgsz,
                batch=a.batch, device=a.device, patience=15,
                workers=a.workers, cache=False, **extra,
                # 합성 데이터에 이미 열화를 넣었으므로 기하 증강만 약하게 건다.
                # 회전·전단을 크게 주면 악보에 없는 배치를 배운다.
                degrees=1.0, shear=1.0, perspective=0.0,
                scale=0.25, translate=0.05, fliplr=0.0, mosaic=a.mosaic,
                project=a.project, name=a.name, exist_ok=True)
    best = Path(a.project) / a.name / "weights" / "best.pt"
    if best.exists():
        YOLO(str(best)).export(format="onnx", imgsz=a.imgsz, simplify=True)
        print(f"→ {best.with_suffix('.onnx')}  (브라우저 배포용)")


if __name__ == "__main__":
    main()
