# -*- coding: utf-8 -*-
"""이미 요약한 영상 ID 저장 (중복 방지)."""
import sqlite3
from pathlib import Path

from pathlib import Path as _Path
_DATA_DIR = _Path("/data") if _Path("/data").exists() else _Path(__file__).parent
DB_PATH = _DATA_DIR / "seen_videos.sqlite"


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS seen_videos (
                video_id TEXT PRIMARY KEY,
                channel_id TEXT,
                channel_title TEXT,
                video_title TEXT,
                summarized_at TEXT
            )
        """)
        conn.commit()


def is_seen(video_id: str) -> bool:
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute("SELECT 1 FROM seen_videos WHERE video_id = ?", (video_id,))
        return cur.fetchone() is not None


def mark_seen(video_id: str, channel_id: str = "", channel_title: str = "", video_title: str = ""):
    import datetime
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO seen_videos (video_id, channel_id, channel_title, video_title, summarized_at) VALUES (?, ?, ?, ?, ?)",
            (video_id, channel_id, channel_title, video_title, datetime.datetime.utcnow().isoformat()),
        )
        conn.commit()
