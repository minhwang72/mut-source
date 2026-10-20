"""
**검출 모델을 불러온다 — LibreYOLO(MIT).**

ultralytics 는 AGPL-3.0 이고, Ultralytics 는 그걸로 학습한 모델까지 AGPL 이라고
본다(같은 프로세스로 import 하면 mut 서버 전체가 공개 대상). 그래서 학습·추론을
MIT 인 LibreYOLO 로 옮겼다 — 의존성 사슬에도 AGPL 이 없다(torch·torchvision·
opencv·pycocotools …).

검출 로직(evaldet 등)은 ultralytics 결과 모양을 그대로 읽는다:
``model.predict(img, imgsz=, conf=, verbose=)[0]`` → ``.names`` · ``.boxes.xyxy/cls/conf``.
LibreYOLO 결과도 같은 이름을 쓰므로, 여기서는 두 가지 차이만 맞춘다 —
결과를 리스트로 감싸고, 정수 imgsz 를 (세로, 가로) 로 바꾼다.
"""
from __future__ import annotations

import os

_CACHE: dict[str, "Detector"] = {}


class Detector:
    def __init__(self, model):
        self.model = model

    @property
    def names(self) -> dict:
        return self.model.names

    def predict(self, img, imgsz=960, conf=0.25, verbose=False, **_kw):
        # ultralytics 의 정수 imgsz 는 '긴 변을 이만큼'으로 비율을 지켜 줄이고
        # 나머지를 채운다. 정사각형 (n, n) 이 같은 배율이다.
        hw = (imgsz, imgsz) if isinstance(imgsz, int) else tuple(imgsz)
        r = self.model.predict(img, conf=conf, imgsz=hw)
        return r if isinstance(r, list) else [r]


def load(path: str) -> Detector:
    """같은 가중치는 한 번만 올린다(한 장에 여러 번 부른다)."""
    if path not in _CACHE:
        from libreyolo import LibreYOLO
        dev = os.environ.get("MUTE_DETECT_DEVICE") or "cpu"
        _CACHE[path] = Detector(LibreYOLO(path, device=dev))
    return _CACHE[path]
