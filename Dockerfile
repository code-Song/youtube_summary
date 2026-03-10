FROM python:3.11-slim

# 작업 디렉토리 설정
WORKDIR /app

# 시스템 패키지
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 의존성 먼저 설치 (캐시 활용)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 복사
COPY . .

# HF Spaces 영구 스토리지 마운트 포인트
RUN mkdir -p /data

# HF Spaces 기본 포트: 7860
EXPOSE 7860

# uvicorn으로 FastAPI 서버 실행
CMD ["uvicorn", "utube_summary:fastapi_app", "--host", "0.0.0.0", "--port", "7860"]
