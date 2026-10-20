"""
**개발용 LLM 디스크 캐시.** 같은 악보를 몇십 번 다시 그려 보며 고치는데,
그때마다 개수·코드 판독에 돈이 나간다. 응답을 이미지 해시로 적어 두면
두 번째부터는 공짜다 — `eval/aicache` 와 같은 자리를 쓰므로 측정 스크립트가
쌓아 둔 캐시도 그대로 쓴다.

**개발 통로(`dev_enabled`)에서만 설치한다.** 배포에서는 호출되지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import os

CACHE = os.environ.get("MUTE_DEV_CACHE") or "eval/aicache"


def _key(tag: str, img) -> str:
    b = img.tobytes() if hasattr(img, "tobytes") else bytes(img)
    return os.path.join(CACHE, f"{tag}-{hashlib.sha1(b).hexdigest()[:16]}.json")


def _save(path: str, obj) -> None:
    """임시 파일에 쓰고 바꿔 끼운다 — 반쪽짜리 캐시를 남기지 않는다."""
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as fh:
            json.dump(obj, fh, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:                                       # noqa: BLE001
        if os.path.exists(tmp):
            os.remove(tmp)


def _load(path: str):
    """깨진 캐시는 없는 것으로 친다."""
    try:
        return json.load(open(path))
    except Exception:                                       # noqa: BLE001
        os.remove(path)
        return None


def install() -> str:
    """개수·코드 판독을 캐시로 감싼다. 쓰는 자리를 돌려준다."""
    import readcounts as RC
    import read_chords as RChd

    os.makedirs(CACHE, exist_ok=True)
    orig_counts, orig_chords = RC.read_page, RChd.read

    def counts(img, *a, **k):
        f = _key("counts", img)
        if os.path.exists(f):
            hit = _load(f)
            if hit is not None:
                return hit
        d = orig_counts(img, *a, **k)
        _save(f, d)
        return d

    def chords(collage, n, *a, **k):
        # pydantic 객체는 그대로 JSON 이 안 된다 — 풀어 적고 되살린다.
        f = _key("chords", collage)
        if os.path.exists(f):
            hit = _load(f)
            if hit is not None:
                return [RChd.ChordRead(**d) for d in hit]
        d = orig_chords(collage, n, *a, **k)
        _save(f, [x.model_dump() for x in d])
        return d

    RC.read_page, RChd.read = counts, chords

    # homr 도 같은 자리에 — 장당 10~20초라 105장 재측정마다 돌리면 30분이 더 든다
    import homr_runner as HR
    orig_homr = HR.read

    def homr(png, *a, **k):
        f = _key("homr2", png)    # 음높이까지 담는 형식
        if os.path.exists(f):
            hit = _load(f)
            if hit is not None:
                return hit
        d = orig_homr(png, *a, **k)
        if d is not None:
            _save(f, d)
        return d

    HR.read = homr
    return CACHE
