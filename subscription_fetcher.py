# -*- coding: utf-8 -*-
"""구독 채널 목록 조회 (OAuth 또는 로컬 파일)."""
from __future__ import annotations

from pathlib import Path
from typing import List

from config import (
    YOUTUBE_CHANNELS_FILE,
    YOUTUBE_CHANNEL_IDS,
    YOUTUBE_CREDENTIALS_PATH,
    YOUTUBE_TOKEN_PATH,
)


def _read_channel_ids_from_file() -> List[str]:
    """channels.txt에서 채널 ID 목록 읽기 (한 줄에 하나)."""
    if not YOUTUBE_CHANNELS_FILE.exists():
        return []
    ids: List[str] = []
    for line in YOUTUBE_CHANNELS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            ids.append(line)
    return ids


def get_channel_ids() -> List[str]:
    """
    구독 채널 ID 목록 반환.
    우선순위: YOUTUBE_CHANNEL_IDS(env) > channels.txt > OAuth API
    """
    if YOUTUBE_CHANNEL_IDS:
        return YOUTUBE_CHANNEL_IDS
    file_ids = _read_channel_ids_from_file()
    if file_ids:
        return file_ids
    oauth_ids = fetch_subscriptions_via_oauth()
    return oauth_ids


def fetch_subscriptions_via_oauth() -> List[str]:
    """OAuth로 YouTube 구독 채널 ID 목록 조회. token 없으면 빈 리스트."""
    if not YOUTUBE_CREDENTIALS_PATH.exists():
        return []

    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as e:
        print(f"[오류] OAuth 패키지 없음: {e}")
        print("  pip install google-auth-oauthlib google-auth")
        return []

    SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]
    creds = None

    if YOUTUBE_TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(YOUTUBE_TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            # 만료된 토큰 자동 갱신 (브라우저 불필요)
            creds.refresh(Request())
            with open(YOUTUBE_TOKEN_PATH, "w") as f:
                f.write(creds.to_json())
        else:
            # 토큰 없음 → 봇 실행 중에는 브라우저 인증 불가
            print("[오류] YouTube OAuth 토큰이 없습니다.")
            print("       봇 실행 전에 먼저 아래 명령어를 실행하세요:")
            print("         python setup_oauth.py")
            return []

    youtube = build("youtube", "v3", credentials=creds)
    channel_ids: List[str] = []

    request = youtube.subscriptions().list(
        part="snippet",
        mine=True,
        maxResults=50,
    )
    while request:
        resp = request.execute()
        for item in resp.get("items", []):
            ch_id = item.get("snippet", {}).get("resourceId", {}).get("channelId")
            if ch_id:
                channel_ids.append(ch_id)
        request = youtube.subscriptions().list_next(request, resp)

    if channel_ids:
        save_channel_ids_to_file(channel_ids)
    return channel_ids


def save_channel_ids_to_file(channel_ids: List[str], path: Path | None = None) -> None:
    """채널 ID 목록을 파일에 저장."""
    path = path or YOUTUBE_CHANNELS_FILE
    path.write_text("\n".join(channel_ids), encoding="utf-8")
