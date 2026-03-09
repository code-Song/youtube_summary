# -*- coding: utf-8 -*-
"""YouTube 구독 채널의 새 영상 조회."""
from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from typing import List, Optional

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import YOUTUBE_API_KEY, DAYS_TO_CHECK
from subscription_fetcher import get_channel_ids

logger = logging.getLogger(__name__)


@dataclass
class VideoInfo:
    video_id: str
    title: str
    channel_id: str
    channel_title: str
    published_at: str
    url: str


def _get_videos_via_playlist(youtube, channel_id: str, channel_title: str, published_after: str) -> Optional[List[VideoInfo]]:
    """업로드 플레이리스트로 새 영상 조회. 실패 시 None 반환."""
    try:
        ch = youtube.channels().list(
            part="contentDetails,snippet",
            id=channel_id,
        ).execute()

        if not ch.get("items"):
            return None

        uploads_playlist_id = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        channel_title = ch["items"][0]["snippet"]["title"]

        pl = youtube.playlistItems().list(
            part="snippet,contentDetails",
            playlistId=uploads_playlist_id,
            maxResults=15,
        ).execute()

        videos: List[VideoInfo] = []
        for item in pl.get("items", []):
            sn = item.get("snippet", {})
            vid = sn.get("resourceId", {}).get("videoId")
            if not vid:
                continue
            pub = sn.get("publishedAt", "")
            if pub < published_after:
                continue
            videos.append(VideoInfo(
                video_id=vid,
                title=sn.get("title", ""),
                channel_id=channel_id,
                channel_title=channel_title,
                published_at=pub,
                url=f"https://www.youtube.com/watch?v={vid}",
            ))
        return videos

    except HttpError as e:
        if e.resp.status == 404:
            return None  # fallback으로 넘김
        raise


def _get_videos_via_search(youtube, channel_id: str, published_after: str) -> List[VideoInfo]:
    """search API로 새 영상 조회 (playlist 접근 불가 채널용 fallback)."""
    try:
        result = youtube.search().list(
            part="snippet",
            channelId=channel_id,
            type="video",
            order="date",
            publishedAfter=published_after,
            maxResults=15,
        ).execute()

        videos: List[VideoInfo] = []
        for item in result.get("items", []):
            vid = item.get("id", {}).get("videoId")
            if not vid:
                continue
            sn = item.get("snippet", {})
            pub = sn.get("publishedAt", "")
            videos.append(VideoInfo(
                video_id=vid,
                title=sn.get("title", ""),
                channel_id=channel_id,
                channel_title=sn.get("channelTitle", ""),
                published_at=pub,
                url=f"https://www.youtube.com/watch?v={vid}",
            ))
        return videos

    except HttpError as e:
        logger.warning("[YouTube] 채널 %s search 조회도 실패: %s", channel_id, e)
        return []


def get_new_videos() -> List[VideoInfo]:
    """구독 채널 목록에서 최근 DAYS_TO_CHECK일 이내 새 영상 조회."""
    if not YOUTUBE_API_KEY:
        raise ValueError("YOUTUBE_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")

    channel_ids = get_channel_ids()
    if not channel_ids:
        raise ValueError(
            "구독 채널이 비어 있습니다. 다음 중 하나를 실행하세요:\n"
            "  1) python setup_oauth.py (OAuth로 자동 수집)\n"
            "  2) .env에 YOUTUBE_CHANNEL_IDS=UCxxx,UCyyy 형태로 직접 입력"
        )

    # file_cache 경고 억제
    import logging as _logging
    _logging.getLogger("googleapiclient.discovery_cache").setLevel(_logging.ERROR)

    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    published_after = (
        datetime.datetime.utcnow() - datetime.timedelta(days=DAYS_TO_CHECK)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    videos: List[VideoInfo] = []
    for channel_id in channel_ids:
        try:
            # 1차 시도: 업로드 플레이리스트
            result = _get_videos_via_playlist(youtube, channel_id, "", published_after)

            if result is None:
                # 2차 시도: search API (fallback)
                logger.info("[YouTube] 채널 %s: 플레이리스트 접근 불가 → search API로 재시도", channel_id)
                result = _get_videos_via_search(youtube, channel_id, published_after)

            videos.extend(result)

        except HttpError as e:
            logger.warning("[YouTube] 채널 %s 조회 실패: %s", channel_id, e)
        except Exception as e:
            logger.warning("[YouTube] 채널 %s 처리 중 오류: %s", channel_id, e)

    videos.sort(key=lambda v: v.published_at, reverse=True)
    return videos
