"""코드가 아닌 글자를 버리고, 붙어 읽힌 코드를 나누는가(read_chords.to_extraction)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from read_chords import ChordRead, to_extraction


def run(texts):
    boxes = [{"system": 0, "x": 100 * i, "y": 0, "w": 70, "h": 20} for i in range(len(texts))]
    reads = [ChordRead(index=i, text=t, is_chord=True, confidence=1.0) for i, t in enumerate(texts)]
    detect = {"systems": [{"index": 0, "staffTop": 50, "staffBottom": 90}], "imageSize": [800, 200]}
    ex = to_extraction(detect, boxes, reads, {})
    return [(c["text"], round(c["box"]["x"])) for c in ex["systems"][0]["chords"]]


def test_directives_dropped_and_merged_split():
    # now0918-3 'Fine'·'D.S.' / camp0814b-02 구역 상자 'C′' / camp0814b-10 'Esus4E7'
    got = run(["G", "Fine", "D.S.", "C′", "Esus4E7", "Bm7/F#"])
    assert [t for t, _ in got] == ["G", "Esus4", "E7", "Bm7/F#"], got
    # 나눈 두 코드는 원래 상자 안에서 왼쪽부터
    assert got[1][1] == 400 and 400 < got[2][1] < 470


if __name__ == "__main__":
    test_directives_dropped_and_merged_split(); print("ok")
