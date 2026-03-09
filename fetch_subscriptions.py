# -*- coding: utf-8 -*-
"""
구독 채널 ID 자동 수집

방법 1 (OAuth): python fetch_subscriptions.py
  - Google OAuth로 구독 목록 조회 후 channels.txt에 저장
  - youtube_credentials.json 필요 (Google Cloud Console에서 OAuth 클라이언트 생성)

방법 2 (브라우저 JS): python fetch_subscriptions.py --from-js
  - 1) https://www.youtube.com/feed/channels 접속 (로그인 필수)
  - 2) 개발자 도구 콘솔(F12)에서 get_channels.js 내용 붙여넣기
  - 3) 출력된 채널 ID를 복사 후 이 스크립트에 붙여넣기
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import YOUTUBE_CHANNELS_FILE
from subscription_fetcher import (
    fetch_subscriptions_via_oauth,
    save_channel_ids_to_file,
)


def parse_csv_from_stdin() -> list[str]:
    """stdin에서 CSV 형식(Channel Id,...) 또는 채널 ID 목록 파싱."""
    lines = sys.stdin.read().strip().splitlines()
    ids: list[str] = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # "UC...,http://...,제목" 형식 또는 "UC..." 한 줄
        if "," in line:
            first = line.split(",")[0].strip()
            if first.startswith("UC") and len(first) == 24:
                ids.append(first)
        elif re.match(r"UC[\w-]{22}", line):
            ids.append(line)
    return ids


def main() -> None:
    if "--from-js" in sys.argv:
        print("채널 ID를 붙여넣으세요 (한 줄에 하나 또는 CSV). 입력 끝나면 Ctrl+Z (Win) / Ctrl+D (Unix):")
        ids = parse_csv_from_stdin()
        if not ids:
            print("채널 ID를 찾을 수 없습니다.")
            sys.exit(1)
        save_channel_ids_to_file(ids)
        print(f"채널 {len(ids)}개 저장: {YOUTUBE_CHANNELS_FILE}")
        return

    print("OAuth로 구독 채널 조회 중... (브라우저가 열리면 로그인)")
    try:
        ids = fetch_subscriptions_via_oauth()
    except Exception as e:
        print(f"오류: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    if not ids:
        print("구독 채널을 가져올 수 없습니다.")
        print("  - youtube_credentials.json 형식 확인 (Desktop 앱 OAuth로 생성)")
        print("  - pip install google-auth-oauthlib 확인")
        print("  - 또는 --from-js 옵션으로 브라우저에서 추출")
        sys.exit(1)
    save_channel_ids_to_file(ids)
    print(f"채널 {len(ids)}개 저장: {YOUTUBE_CHANNELS_FILE}")


if __name__ == "__main__":
    main()
