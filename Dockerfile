# 뮤트 서버 — CPU 전용. 서버는 구조 데이터만 만들고 악보 이미지는 안 만든다.
# 코드 텍스트 판정은 TS 코어 파서가 한다(결정론적) — node 가 필요하다
FROM node:22-slim AS node

FROM python:3.12-slim
COPY --from=node /usr/local/bin/node /usr/local/bin/node

# opencv(ultralytics 의존)가 libGL·libglib 을 찾는다
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# torch 는 CPU 휠로. 기본 휠은 CUDA 를 끌고 와 이미지가 몇 GB 더 커진다
# **torchvision 을 빼면 안 된다.** YOLO 의 NMS 가 torchvision 연산자라,
# 없으면 검출이 통째로 실패한다 — 그런데 LLM 경로는 그대로 돌아서 작업은
# "성공"으로 끝나고 음표만 0개가 된다(실측: struct.error
# "operator torchvision::nms does not exist", 사이트에서 변환 불가).
RUN pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        torch==2.14.0 torchvision==0.29.0
RUN pip install --no-cache-dir \
        ultralytics==8.4.150 anthropic==0.115.0 pydantic==2.13.4 \
        numpy==2.4.2 pillow==12.1.1

# ultralytics 익명 통계 끄기 — 사용자 악보를 다루는 서버라 밖으로 나가는 건 다 막는다
ENV YOLO_CONFIG_DIR=/tmp/ultralytics MPLCONFIGDIR=/tmp/mpl
RUN mkdir -p /tmp/ultralytics && yolo settings sync=False 2>/dev/null || true

WORKDIR /app
COPY tools/ tools/
COPY server/ server/
COPY web/ web/
COPY src/ src/
COPY package.json ./
COPY models/omr.pt models/omr_tie.pt models/classes.txt models/

ENV PYTHONUNBUFFERED=1
EXPOSE 3000
CMD ["python", "server/serve.py", "--port", "3000", "--host", "0.0.0.0"]
