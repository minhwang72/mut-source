"""
LLM 개수 캐시를 현재 오선 검출에 맞춰 갱신한다.

왜: 캐시는 **단 인덱스로** 개수를 담는다. 오선 구제로 단 수가 바뀐 장은
인덱스가 통째로 어긋나 캐시가 거짓말을 한다. 단 수가 다르거나 캐시에 없는
장만 다시 읽는다 — 나머지는 돈이 안 나간다.
"""
import sys, os, glob, json, time, warnings
sys.path.insert(0, "tools"); sys.path.insert(0, "server")
warnings.filterwarnings("ignore")
from PIL import Image
import prepare, readcounts as RC

CACHE = "eval/llm_counts_cache.json"
cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
todo = []
for p in sorted(glob.glob("악보샘플/이미지/*.png")):
    name = os.path.basename(p)[:-4]
    try:
        img = prepare.load(open(p, "rb"))
        _r, _i, _k, staves = prepare.analyze_image(img)
    except Exception as e:
        print(f"{name}: 건너뜀 ({str(e)[:40]})", flush=True); continue
    c = cache.get(name)
    rows = (c.get("systems") if isinstance(c, dict) else c) if c else None
    if rows is None or len(rows) != len(staves):
        todo.append((name, p, len(rows) if rows else 0, len(staves)))

print(f"다시 읽을 장 {len(todo)} · 예상 비용 ${len(todo)*0.094:.2f}", flush=True)
for n, _p, a, b in todo[:40]:
    print(f"   {n:16s} 캐시 {a}단 → 현재 {b}단", flush=True)

t0 = time.time()
for i, (name, p, _a, _b) in enumerate(todo, 1):
    try:
        cache[name] = RC.read_page(Image.open(p).convert("RGB"))
        json.dump(cache, open(CACHE, "w"), ensure_ascii=False)
        print(f"  {i}/{len(todo)} {name} ok ({(time.time()-t0)/60:.0f}분)", flush=True)
    except Exception as e:
        print(f"  {i}/{len(todo)} {name} 실패: {str(e)[:60]}", flush=True)
print(f"완료 · 캐시 {len(cache)}장")
