# -*- coding: utf-8 -*-
"""설정: .env 또는 환경변수에서 로드."""
import os
import json
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

# ── 스토리지 경로 ────────────────────────────────────────────────────
# HF Spaces의 /data 는 컨테이너 재시작 후에도 유지되는 영구 스토리지
# 로컬에서는 프로젝트 폴더를 그대로 사용
_DATA_DIR = Path("/data") if Path("/data").exists() else Path(__file__).parent

# YouTube Data API v3
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
YOUTUBE_CHANNEL_IDS = [
    x.strip()
    for x in os.environ.get("YOUTUBE_CHANNEL_IDS", "").split(",")
    if x.strip()
]

# OAuth 인증 파일 경로 (영구 스토리지 사용)
YOUTUBE_CREDENTIALS_PATH = Path(__file__).parent / "youtube_credentials.json"
YOUTUBE_TOKEN_PATH = _DATA_DIR / "youtube_token.json"

# 구독 채널 ID 파일 (영구 스토리지 사용)
YOUTUBE_CHANNELS_FILE = _DATA_DIR / "channels.txt"

# ── HF Spaces Secret에서 파일 복원 ──────────────────────────────────
# HF Spaces는 파일 업로드가 불가하므로, Secret에 파일 내용을 문자열로 저장 후 복원

def _restore_secret_file(env_var: str, target_path: Path):
    """환경변수에 저장된 파일 내용을 실제 파일로 복원."""
    content = os.environ.get(env_var, "")
    if content and not target_path.exists():
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(content, encoding="utf-8")

# youtube_token.json 복원 (Secret: YOUTUBE_TOKEN_JSON)
_restore_secret_file("YOUTUBE_TOKEN_JSON", YOUTUBE_TOKEN_PATH)

# channels.txt 복원 (Secret: YOUTUBE_CHANNELS_TXT)
_restore_secret_file("YOUTUBE_CHANNELS_TXT", YOUTUBE_CHANNELS_FILE)

# Gemini (요약용)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-1.5-pro")

# Telegram
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# 스케줄 (매일 6시, 한국 시간)
DAILY_HOUR = int(os.environ.get("DAILY_HOUR", "6"))
DAILY_MINUTE = int(os.environ.get("DAILY_MINUTE", "0"))
TIMEZONE = os.environ.get("TZ", "Asia/Seoul")

# 새 영상 조회 범위 (최근 N일)
DAYS_TO_CHECK = int(os.environ.get("DAYS_TO_CHECK", "1"))
