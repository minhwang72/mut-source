"""분할본은 복사하지 않고 하드링크한다 — 디스크를 두 배로 쓰지 않는다."""
import os, sys, tempfile
from pathlib import Path
sys.path.insert(0, os.path.dirname(__file__))
import train as T

with tempfile.TemporaryDirectory() as tmp:
    src = Path(tmp) / "synth"
    (src / "images").mkdir(parents=True); (src / "labels").mkdir()
    for i in range(10):
        (src / "images" / f"{i:03d}.png").write_bytes(b"PNG" * 400)
        (src / "labels" / f"{i:03d}.txt").write_text("0 .5 .5 .1 .1\n")
    (src / "classes.txt").write_text("notehead_filled\naug_dot\n")

    out = Path(tmp) / "yolo"
    yaml = T.split(src, out, val_ratio=0.2, seed=1)
    assert yaml.exists()

    imgs = list((out / "images").rglob("*.png"))
    assert len(imgs) == 10, imgs
    # 하드링크면 inode 가 같다 = 공간을 새로 안 쓴다
    for d in imgs:
        s = src / "images" / d.name
        assert os.stat(d).st_ino == os.stat(s).st_ino, f"복사됐다: {d.name}"

    # 원본을 고치면 분할본에도 보인다 (같은 실체)
    (src / "images" / "000.png").write_bytes(b"CHANGED")
    same = next(p for p in imgs if p.name == "000.png")
    assert same.read_bytes() == b"CHANGED"

    # 두 번째 호출은 이미 있는 것을 다시 만들지 않는다
    before = {p: os.stat(p).st_ino for p in imgs}
    T.split(src, out, val_ratio=0.2, seed=1)
    for p, ino in before.items():
        assert os.stat(p).st_ino == ino, f"다시 만들었다: {p.name}"

    txt = yaml.read_text()
    assert "nc: 2" in txt and "aug_dot" in txt, txt

print("ok — 하드링크 분할 · 재실행 시 그대로")
