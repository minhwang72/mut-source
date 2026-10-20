"""
**없던 쉼표가 어디서 들어오나.** 원본과 0도 이조로 대조하니 음표 자리에
쉼표가 끼어 있었다. 후보는 셋이다 —
  ① 개수 LLM 이 쉼표를 많이 세어, `detect_guided` 가 그 수를 채우려
     낮은 점수 상자를 쉼표로 올린다
  ② 못 읽은 빈 마디를 온쉼표로 채운다
  ③ fit_page 가 박자를 맞추려 넣는다
단별로 LLM 이 센 수와 구조에 남은 수를 나란히 놓으면 ①인지 바로 보인다.
"""
import os, sys, json, hashlib, warnings, collections
sys.path.insert(0, "tools"); sys.path.insert(0, "server")
warnings.filterwarnings("ignore")

CACHE = "eval/aicache"


def _key(tag, img):
    b = img.tobytes() if hasattr(img, "tobytes") else bytes(img)
    return f"{CACHE}/{tag}-{hashlib.sha1(b).hexdigest()[:16]}.json"


def install_cache():
    """LLM 두 곳을 **캐시 전용**으로 감싼다 — 없으면 그대로 부른다."""
    import readcounts as RC, read_chords as RChd
    oc, och = RC.read_page, RChd.read

    def counts(img, *a, **k):
        f = _key("counts", img)
        if os.path.exists(f):
            return json.load(open(f))
        return oc(img, *a, **k)

    def chords(collage, n, *a, **k):
        f = _key("chords", collage)
        if os.path.exists(f):
            return [RChd.ChordRead(**d) for d in json.load(open(f))]
        return och(collage, n, *a, **k)

    RC.read_page, RChd.read = counts, chords


install_cache()
import serve                                                  # noqa: E402

serve.STATE["mode"] = "ai"
LLM = json.load(open("eval/llm_counts_cache.json"))
tot = collections.Counter()
for name in (sys.argv[1:] or ["day2sb-1"]):
    ex = serve.read_sheet(open(f"악보샘플/이미지/{name}.png", "rb").read(), None)
    st = ex.get("struct") or {}
    by = {c["system"]: c for c in (LLM.get(name, {}).get("systems") or [])}
    print(f"\n== {name}   (LLM 음표/쉼표 → 구조 음표/쉼표)")
    print("  단   음표            쉼표          fitted guessed 빈마디")
    for s in st.get("systems") or []:
        i = s.get("system")
        ns = s.get("notes") or []
        nn = sum(1 for n in ns if not n.get("rest"))
        nr = sum(1 for n in ns if n.get("rest"))
        fit = sum(1 for n in ns if n.get("fitted"))
        gs = sum(1 for n in ns if n.get("guessed"))
        empty = s.get("measures", 0) - len({n.get("measure") for n in ns})
        c = by.get(i, {})
        ln, lr = c.get("notes", "?"), c.get("rests", "?")
        dn = nn - ln if isinstance(ln, int) else 0
        dr = nr - lr if isinstance(lr, int) else 0
        tot["쉼표 초과"] += max(0, dr); tot["쉼표 부족"] += max(0, -dr)
        tot["음표 초과"] += max(0, dn); tot["음표 부족"] += max(0, -dn)
        tot["fitted"] += fit; tot["guessed"] += gs; tot["빈 마디"] += max(0, empty)
        print(f"  {i:2}  {ln:3} → {nn:3} ({dn:+3})   {lr:3} → {nr:3} ({dr:+3})"
              f"  {fit:5} {gs:6} {max(0,empty):5}")
print("\n합계", dict(tot))
