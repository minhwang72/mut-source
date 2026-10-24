#!/usr/bin/env python3
"""
**운영 검출기에서 이어 펜·형광펜 합성으로 미세조정한다.**

    python tools/train_pen.py data/yolo_pen6k/data.yaml --name pen6k

증강은 운영 모델이 학습한 값(체크포인트의 train_args)을 그대로 쓰고, 악보에 해로운
것만 끈다 — 좌우·상하 뒤집기(높낮이·기둥 방향이 뒤집힌다), mixup(두 악보가 겹친다).
2026-10-21 pen6k(12에폭, lr0 0.002): 105장 통과 25 → 28 (models/omr.pt 로 교체).
"""
import argparse

from ultralytics import YOLO

ap = argparse.ArgumentParser()
ap.add_argument("data")
ap.add_argument("--model", default="models/omr.pt")
ap.add_argument("--name", required=True)
ap.add_argument("--epochs", type=int, default=12)
ap.add_argument("--lr0", type=float, default=0.002)
ap.add_argument("--batch", type=int, default=16)
a = ap.parse_args()

m = YOLO(a.model)
t = m.ckpt.get("train_args", {})
m.train(data=a.data, epochs=a.epochs, imgsz=960, batch=a.batch, device="mps",
        workers=6, project="runs_ultra", name=a.name, exist_ok=True,
        scale=t.get("scale", 0.25), translate=t.get("translate", 0.05),
        degrees=t.get("degrees", 1.0), shear=t.get("shear", 1.0),
        hsv_h=t.get("hsv_h", 0.015), hsv_s=t.get("hsv_s", 0.7), hsv_v=t.get("hsv_v", 0.4),
        fliplr=0.0, flipud=0.0, mosaic=t.get("mosaic", 0.3), mixup=0.0,
        close_mosaic=4, lr0=a.lr0, warmup_epochs=0, plots=False, verbose=False)
