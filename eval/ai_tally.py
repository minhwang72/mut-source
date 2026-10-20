"""
**배포된 ai 경로를 그대로 잰다.**

지금까지 잰 103장은 전부 local 경로였다. 그런데 배포는 ai 경로이고,
거기에만 있는 차단 사유가 있다 — "기존 개수 판독 N개와 검출 M개 불일치".
LLM 이 센 음표 수와 검출기가 찾은 수가 다를 때 나는데, local 은 개수를
LLM 에 안 물으니 이 사유가 아예 없다. 실서비스 1위 차단 사유를 못 보고
있었던 셈이다.

**LLM 응답을 디스크에 캐시한다.** 한 번 돈을 쓰면 이후 측정은 공짜다 —
같은 악보로 실험을 반복해야 하므로 이게 없으면 매번 과금된다.
"""
import os, sys, json, hashlib, warnings, collections
sys.path.insert(0, "tools"); sys.path.insert(0, "server")
warnings.filterwarnings("ignore")

CACHE = "eval/aicache"
os.makedirs(CACHE, exist_ok=True)


def _key(tag, img):
    b = img.tobytes() if hasattr(img, "tobytes") else bytes(img)
    return f"{CACHE}/{tag}-{hashlib.sha1(b).hexdigest()[:16]}.json"


def _save(f, obj) -> bool:
    """**임시 파일에 쓰고 바꿔 끼운다.** 쓰다 실패하면 반쪽짜리 파일이
    남는데, 다음 실행이 그걸 캐시로 읽고 깨진다(실측으로 당했다)."""
    tmp = f + ".tmp"
    try:
        with open(tmp, "w") as fh:
            json.dump(obj, fh, ensure_ascii=False)
        os.replace(tmp, f)
        return True
    except TypeError:
        os.path.exists(tmp) and os.remove(tmp)
        return False


def _load(f):
    """깨진 캐시는 없는 것으로 친다."""
    try:
        return json.load(open(f))
    except Exception:                            # noqa: BLE001
        os.remove(f)
        return None


def install_cache():
    """LLM 두 곳을 캐시로 감싼다. 없으면 부르고, 있으면 파일에서 읽는다."""
    import readcounts as RC
    import read_chords as RChd

    orig_counts, orig_chords = RC.read_page, RChd.read
    calls = collections.Counter()

    def counts(img, *a, **k):
        f = _key("counts", img)
        if os.path.exists(f):
            hit = _load(f)
            if hit is not None:
                calls["counts-hit"] += 1
                return hit
        calls["counts-miss"] += 1
        d = orig_counts(img, *a, **k)
        if not _save(f, d):
            print("  개수 캐시 실패 — 다음에도 LLM 을 부른다", file=sys.stderr)
        return d

    def chords(collage, n, *a, **k):
        # **pydantic 객체는 그냥 JSON 으로 안 들어간다.** 받아 적을 때
        # model_dump 로 풀고, 꺼낼 때 같은 형으로 되살린다 — dict 를
        # 돌려주면 호출부가 .text 를 못 읽는다.
        f = _key("chords", collage)
        if os.path.exists(f):
            hit = _load(f)
            if hit is not None:
                calls["chords-hit"] += 1
                return [RChd.ChordRead(**d) for d in hit]
        calls["chords-miss"] += 1
        d = orig_chords(collage, n, *a, **k)
        _save(f, [x.model_dump() for x in d])
        return d

    RC.read_page, RChd.read = counts, chords
    # serve 가 함수 안에서 import 하므로 모듈 객체를 갈아 끼우면 된다
    return calls


calls = install_cache()
import serve
import db as DB

# 인자가 숫자 하나면 "그만큼 고르게 뽑아라"는 뜻이다. 셸에서 파일 목록을
# 넘기다 경로가 깨진 적이 있어, 고르는 일을 여기서 한다.
_all = sorted(f"악보샘플/이미지/{f}" for f in os.listdir("악보샘플/이미지")
              if f.endswith(".png"))
if len(sys.argv) == 2 and sys.argv[1].isdigit():
    k = int(sys.argv[1])
    step = max(1, len(_all) // k)
    PAGES = _all[::step][:k]
else:
    PAGES = sys.argv[1:] or _all

serve.STATE["mode"] = "ai"
kinds, rows, errs = collections.Counter(), [], 0
pages_with = collections.Counter()
for p in PAGES:
    name = os.path.basename(p)[:-4]
    try:
        ex = serve.read_sheet(open(p, "rb").read(), None)
        g = serve.local_reader.quality_gate(ex, []) if hasattr(serve, "local_reader") \
            else ex.get("qualityGate")
        if g is None:
            import local_reader as LR
            g = LR.quality_gate(ex, [])
    except Exception as e:                       # noqa: BLE001
        errs += 1
        print(f"{name:18} 오류 {type(e).__name__}: {str(e)[:60]}", flush=True)
        continue
    ks = [DB.issue_kind(m) for m in (g.get("blocking") or [])]
    kinds.update(ks)
    for k in set(ks):
        pages_with[k] += 1
    st = ex.get("struct") or {}
    rows.append({"page": name, "gate": g["status"], "n": len(ks),
                 "systems": len(st.get("systems") or []), "kinds": ks})
    print(f"{name:18} {g['status']:13} 차단 {len(ks):3} · 단 "
          f"{len(st.get('systems') or []):2}", flush=True)

ok = sum(1 for r in rows if r["n"] == 0)
n = max(1, len(rows))
print(f"\n== {len(rows)}장 (오류 {errs}) · LLM 호출 {dict(calls)}")
print(f"통과 {ok}장 ({ok/n:.0%}) · 장당 차단 사유 "
      f"{sum(r['n'] for r in rows)/n:.1f}")
print("\n차단 사유 (건수 · 장 수)")
for k, c in kinds.most_common(14):
    print(f"  {c:5}  {pages_with[k]:3}장  {k}")
json.dump(rows, open("eval/ai_tally.json", "w"), ensure_ascii=False, indent=1)
