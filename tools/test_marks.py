"""사람 표시가 **양성 라벨을 망가뜨리지 않는가**.

형광펜은 오선을 통째로 덮고 손글씨는 음표 위를 지난다 — 실제 악보가 그렇다.
그런데 표시가 머리를 가려 버리면 "여기 음표 있다"는 라벨이 거짓이 되고,
검출기는 안 보이는 것을 찾도록 배운다. 그게 이 검사가 막는 것이다.
"""
import os, random, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import gendata as G
import musicxml as M

worst, checked = 255, 0
for seed in range(12):
    rng = random.Random(seed)
    ms, f = G.random_score(rng, 4)
    img, boxes = G.render_sample(M.build(ms, fifths=f), G.random_style(rng))
    if img is None or not boxes:
        continue
    heads = [b for b in boxes if b["class"].startswith("notehead")]
    if not heads:
        continue
    for s2 in range(6):
        out = G.human_marks(img, boxes, random.Random(seed * 100 + s2))
        assert out.size == img.size, "표시가 이미지 크기를 바꿨다"
        a = np.asarray(out).astype(int)
        for b in heads:
            y0, y1 = int(b["y"]), int(b["y"] + b["h"])
            x0, x1 = int(b["x"]), int(b["x"] + b["w"])
            patch = a[max(0, y0):y1, max(0, x0):x1]
            if patch.size == 0:
                continue
            worst = min(worst, int(patch.min()))
            checked += 1
            # 머리 자리에 **짙은 잉크가 남아 있어야** 라벨이 참이다
            assert patch.min() < 120, (
                f"머리가 표시에 지워졌다 (seed {seed}/{s2}, 최소 화소 {patch.min()})")

assert checked > 100, f"검사한 머리가 너무 적다 ({checked})"
print(f"ok — 머리 {checked}개 확인 · 가장 밝았던 머리 화소 {worst}")
