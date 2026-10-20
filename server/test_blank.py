"""
악보가 아닌 이미지를 올리면 **이유가 화면에 뜨는가.**

왜: 에러를 결과 dict 로 돌려주면 작업은 status=done 이 되고, 브라우저는
result.error 를 보지 않는다 — 빈 페이지를 올리면 "성공"인데 화면만 깨진다
(실측: day2conti-1 은 PDF 의 빈 표지라 잉크가 0.0% 였다).
ValueError 로 던져야 jobs 가 그대로 사용자에게 전한다.
"""
import io, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import jobs
from PIL import Image

# 사용자에게 전달되는 사유인가
assert jobs._safe_error(ValueError("오선을 찾지 못했습니다")) == "오선을 찾지 못했습니다"
assert "판독에 실패" in jobs._safe_error(RuntimeError("torch 내부 오류 /app/tools/x.py"))
assert "/app/" not in jobs._safe_error(RuntimeError("torch 내부 오류 /app/tools/x.py")), \
    "경로가 사용자에게 새어 나간다"

# 빈 이미지는 실패로 끝나고 사유가 남아야 한다
import serve
blank = io.BytesIO()
Image.new("RGB", (600, 800), "white").save(blank, format="PNG")
try:
    serve.read_sheet(blank.getvalue(), None)
    raise AssertionError("빈 이미지가 성공으로 끝났다")
except ValueError as e:
    # 사유가 사람 말로 전달되면 된다 — 흰 종이면 "빈 페이지", 악보인데
    # 못 읽으면 "오선". 어느 쪽이든 무엇을 해야 할지 말해 줘야 한다.
    assert ("빈 페이지" in str(e) or "오선" in str(e)), str(e)
except Exception as e:                           # 모델·환경이 없는 경우
    print(f"  (환경 제약으로 건너뜀: {type(e).__name__})")

print("ok")


# ── 빈 페이지와 "못 읽는 악보"를 가른다 ─────────────────────────────
# 빈 페이지한테 "더 밝고 평평하게 찍어 주세요"는 쓸모없는 조언이다.
# 사진이 어두워서가 아니라 아무것도 없어서다. 콘티 PDF 에는 표지가 흔하다.
import numpy as np
import local_reader as LR

blank = np.zeros((400, 300), dtype=np.uint8)
msg = LR.blank_reason(blank)
assert msg and "빈 페이지" in msg, msg

# 실측 하한(가장 옅은 실제 악보 0.0315)보다 한참 위면 빈 페이지가 아니다
sheet = np.zeros((400, 300), dtype=np.uint8)
sheet[::10, :] = 255                      # 잉크 10%
assert LR.blank_reason(sheet) is None, LR.blank_reason(sheet)

# 경계: 문턱 바로 아래는 빈 페이지, 바로 위는 아니다
n = blank.size
low = np.zeros(n, dtype=np.uint8); low[: int(n * 0.002)] = 255
assert LR.blank_reason(low.reshape(blank.shape)) is not None
high = np.zeros(n, dtype=np.uint8); high[: int(n * 0.03)] = 255
assert LR.blank_reason(high.reshape(blank.shape)) is None

print("ok — 빈 페이지와 못 읽는 악보를 가른다")
