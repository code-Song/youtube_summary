# -*- coding: utf-8 -*-
"""
[최초 1회 실행] Google OAuth 인증 + 구독 채널 목록 저장
봇 실행 전에 이 스크립트를 먼저 실행해서 youtube_token.json을 만드세요.

실행:
    python setup_oauth.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import (
    YOUTUBE_CHANNELS_FILE,
    YOUTUBE_CREDENTIALS_PATH,
    YOUTUBE_TOKEN_PATH,
)


def main():
    if not YOUTUBE_CREDENTIALS_PATH.exists():
        print(f"[오류] 인증 파일이 없습니다: {YOUTUBE_CREDENTIALS_PATH}")
        print("Google Cloud Console에서 OAuth 클라이언트 ID를 다운로드해서")
        print(f"  {YOUTUBE_CREDENTIALS_PATH}  로 저장하세요.")
        sys.exit(1)

    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as e:
        print(f"[오류] 패키지 없음: {e}")
        print("  pip install google-auth-oauthlib google-api-python-client")
        sys.exit(1)

    SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]
    creds = None

    # 기존 토큰 확인
    if YOUTUBE_TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(YOUTUBE_TOKEN_PATH), SCOPES)
        if creds and creds.valid:
            print(f"[OK] 유효한 토큰이 이미 존재합니다: {YOUTUBE_TOKEN_PATH}")
        elif creds and creds.expired and creds.refresh_token:
            print("[INFO] 토큰 만료 → 자동 갱신 중...")
            creds.refresh(Request())
            print("[OK] 토큰 갱신 완료")
        else:
            creds = None  # 재인증 필요

    # 토큰이 없거나 유효하지 않으면 브라우저 인증
    if not creds or not creds.valid:
        print("[INFO] 브라우저에서 Google 로그인 창이 열립니다...")
        flow = InstalledAppFlow.from_client_secrets_file(
            str(YOUTUBE_CREDENTIALS_PATH), SCOPES
        )
        creds = flow.run_local_server(port=8080)
        print("[OK] 인증 완료!")

    # 토큰 저장
    YOUTUBE_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(YOUTUBE_TOKEN_PATH, "w") as f:
        f.write(creds.to_json())
    print(f"[OK] 토큰 저장됨: {YOUTUBE_TOKEN_PATH}")

    # 구독 채널 목록 가져오기
    print("[INFO] YouTube 구독 채널 목록 조회 중...")
    youtube = build("youtube", "v3", credentials=creds)
    channel_ids: list[str] = []

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

    print(f"[OK] 구독 채널 {len(channel_ids)}개 발견")

    if channel_ids:
        YOUTUBE_CHANNELS_FILE.write_text("\n".join(channel_ids), encoding="utf-8")
        print(f"[OK] 채널 목록 저장됨: {YOUTUBE_CHANNELS_FILE}")
        print("\n이제 봇을 실행하세요:")
        print("  python utube_summary.py")
    else:
        print("[경고] 구독 채널이 없거나 조회 실패. channels.txt를 직접 작성하세요.")


if __name__ == "__main__":
    main()
