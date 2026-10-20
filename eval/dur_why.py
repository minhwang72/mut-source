"""
**남은 오류는 음가인가 검출인가.** 0도 이조 대조에서 그림은 맞아졌는데
음가가 다른 마디가 남았다. 정답 악보가 없으니 **박자를 심판으로** 쓴다 —
4/4면 마디 합이 정확히 4박이어야 한다.

  · 0.5박 어긋남 = 음가를 한 단계 잘못 읽었다(점·꼬리)  → 음가 판독
  · 정수 박 어긋남 = 음표가 통째로 빠졌다/늘었다        → 검출
셋은 고칠 자리가 다르다.

**LLM 은 부르지 않는다.** 개수는 `eval/llm_counts_cache.json`(103장)에서
이름으로 꺼내고, 코드는 받아 둔 캐시가 있을 때만 쓴다 — 없으면 빈 읽기로
둔다(음가와 무관하다). 한 푼도 안 든다.
"""
import os, sys, json, hashlib, warnings, collections
sys.path.insert(0, "tools"); sys.path.insert(0, "server")
warnings.filterwarnings("ignore")

CACHE = "eval/aicache"
LLM = json.load(open("eval/llm_counts_cache.json"))
stub_chords = collections.Counter()


def install():
    import readcounts as RC, read_chords as RChd

    def counts(img, *a, **k):
        name = counts.page
        if name not in LLM:
            raise RuntimeError(f"개수 캐시 없음: {name}")
        return LLM[name]

    def chords(collage, n, *a, **k):
        b = collage.tobytes() if hasattr(collage, "tobytes") else bytes(collage)
        f = f"{CACHE}/chords-{hashlib.sha1(b).hexdigest()[:16]}.json"
        if os.path.exists(f):
            try:                      # 옛 형식 캐시는 없는 것으로 친다
                return [RChd.ChordRead(**d) for d in json.load(open(f))]
            except Exception:                                 # noqa: BLE001
                pass
        stub_chords[counts.page] += 1
        return [RChd.ChordRead(index=i + 1, is_chord=False, text="", confidence=0.0)
                for i in range(n)]

    RC.read_page, RChd.read = counts, chords
    return counts


_c = install()
import serve                                                  # noqa: E402
import checkbeats as CB                                       # noqa: E402

serve.STATE["mode"] = "ai"
PAGES = sys.argv[1:] or sorted(
    f[:-4] for f in os.listdir("악보샘플/이미지")
    if f.endswith(".png") and f[:-4] in LLM)

dev = collections.Counter()
flags = collections.Counter()
rows, bad_pages, errs = [], 0, 0
for name in PAGES:
    _c.page = name
    try:
        ex = serve.read_sheet(open(f"악보샘플/이미지/{name}.png", "rb").read(), None)
    except Exception as e:                                    # noqa: BLE001
        errs += 1
        print(f"{name:16} 오류 {type(e).__name__}: {str(e)[:50]}", flush=True)
        continue
    st = ex.get("struct") or {}
    if not st.get("systems"):
        errs += 1
        continue
    beats = int(st.get("beats") or 4)
    per = CB.beats_per_measure(st)
    skip = {(i, m) for i, m, _ in CB.splits(per, beats * 8)}
    # 쪼개진 마디의 뒤 반쪽도 뺀다
    skip |= {(i + 1, f) for i, _, f in CB.splits(per, beats * 8)}
    nbad = 0
    for i, pm in enumerate(per):
        for m, v in pm.items():
            if (i, m) in skip:
                continue
            d = (v - beats * 8) / 8.0
            dev[d if abs(d) <= 4 else ("초과" if d > 0 else "부족")] += 1
            if d:
                nbad += 1
    fit = sum(1 for s in st["systems"] for n in s.get("notes") or [] if n.get("fitted"))
    gs = sum(1 for s in st["systems"] for n in s.get("notes") or [] if n.get("guessed"))
    flags["fitted"] += fit; flags["guessed"] += gs
    tot = sum(len(p) for p in per)
    rows.append((name, tot, nbad))
    bad_pages += 1 if nbad else 0
    print(f"{name:16} 마디 {tot:3} · 어긋남 {nbad:3} · fitted {fit:3} · guessed {gs:3}",
          flush=True)

n = max(1, len(rows))
tot_m = sum(r[1] for r in rows); tot_b = sum(r[2] for r in rows)
print(f"\n== {len(rows)}장 (오류 {errs}) · 코드 캐시 없는 장 {len(stub_chords)}")
print(f"마디 {tot_m} · 박자 어긋남 {tot_b} ({tot_b/max(1,tot_m):.1%}) · "
      f"어긋난 장 {bad_pages}/{n}")
print(f"flags {dict(flags)}")
print("\n어긋남 분포 (박)")
for d, c in sorted(dev.items(), key=lambda kv: -kv[1])[:16]:
    print(f"  {str(d):>7}  {c:5}")
json.dump([{"page": r[0], "measures": r[1], "bad": r[2]} for r in rows],
          open("eval/dur_why.json", "w"), ensure_ascii=False, indent=1)
