# -*- coding: utf-8 -*-
"""
구독 유튜버 새 영상 요약 서비스
- 매일 아침 6시 요약 전송
- 텔레그램에서 "요약해줘" 등 메시지 보내면 즉시 요약 전송 (스트리밍)
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).parent))

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import (
    DAILY_HOUR,
    DAILY_MINUTE,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    TIMEZONE,
)
from storage import is_seen, mark_seen
from summarizer import get_transcript, summarize_video, summarize_with_gemini_stream
from youtube_fetcher import VideoInfo, get_new_videos

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# 전역: 보낼 chat_id (첫 메시지에서 설정)
_send_chat_id: str | None = TELEGRAM_CHAT_ID or None


async def _send_telegram(chat_id: str, text: str):
    """텔레그램으로 메시지 전송 (4096자 제한 처리)."""
    from telegram import Bot
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    for i in range(0, len(text), 4096):
        await bot.send_message(chat_id=chat_id, text=text[i:i + 4096])


async def _do_summarize_and_send(chat_id: str):
    """새 영상 조회 → 스트리밍 요약 → 실시간 텔레그램 전송."""
    from telegram import Bot
    bot = Bot(token=TELEGRAM_BOT_TOKEN)

    try:
        videos = get_new_videos()
        new_ones = [v for v in videos if not is_seen(v.video_id)]
        if not new_ones:
            await _send_telegram(chat_id, "🆕 오늘 새 영상이 없습니다.")
            return

        await _send_telegram(chat_id, f"🔍 새 영상 {len(new_ones)}개를 요약합니다...")

        for idx, video in enumerate(new_ones, 1):
            # ── 1) 시작 메시지 전송 ──────────────────────────────────────
            header = (
                f"📺 [{idx}/{len(new_ones)}] {video.channel_title}\n"
                f"제목: {video.title}\n"
                f"{video.url}\n\n"
                f"📝 요약 중..."
            )
            sent = await bot.send_message(chat_id=chat_id, text=header)
            msg_id = sent.message_id

            transcript = get_transcript(video.video_id)

            # ── 2) 자막 없는 경우 ────────────────────────────────────────
            if not transcript:
                no_sub = (
                    f"📺 [{idx}/{len(new_ones)}] {video.channel_title}\n"
                    f"제목: {video.title}\n"
                    f"{video.url}\n\n"
                    f"⚠️ 자막 없음 - 요약 불가"
                )
                await bot.edit_message_text(
                    chat_id=chat_id, message_id=msg_id, text=no_sub
                )
                mark_seen(video.video_id, video.channel_id, video.channel_title, video.title)
                continue

            # ── 3) Gemini 스트리밍 요약 ──────────────────────────────────
            accumulated = ""
            last_sent_len = 0

            async def on_chunk(part: str, _msg_id=msg_id, _idx=idx, _video=video):
                nonlocal accumulated, last_sent_len
                accumulated += part
                # 80자 이상 쌓이거나 문장 종결 부호면 메시지 편집
                new_chars = len(accumulated) - last_sent_len
                ends_sentence = accumulated and accumulated[-1] in (".", "!", "?", "\n")
                if new_chars >= 80 or ends_sentence:
                    preview = (
                        f"📺 [{_idx}/{len(new_ones)}] {_video.channel_title}\n"
                        f"제목: {_video.title}\n"
                        f"{_video.url}\n\n"
                        f"📝 요약 중...\n{accumulated}▌"
                    )
                    try:
                        await bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=_msg_id,
                            text=preview[:4096],
                        )
                        last_sent_len = len(accumulated)
                    except Exception:
                        pass  # rate limit 등은 무시

            try:
                summary = await summarize_with_gemini_stream(
                    transcript, video.title, on_chunk
                )
                mark_seen(video.video_id, video.channel_id, video.channel_title, video.title)
            except Exception as e:
                logger.exception("요약 실패: %s", video.video_id)
                summary = f"(요약 실패: {e})"
                mark_seen(video.video_id, video.channel_id, video.channel_title, video.title)

            # ── 4) 최종 완성 메시지로 편집 ──────────────────────────────
            final_text = (
                f"📺 [{idx}/{len(new_ones)}] {video.channel_title}\n"
                f"제목: {video.title}\n"
                f"{video.url}\n\n"
                f"✅ 요약 완료:\n{summary}"
            )
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=msg_id,
                    text=final_text[:4096],
                )
            except Exception:
                # 편집 실패 시 새 메시지로 전송
                await _send_telegram(chat_id, final_text)

        await _send_telegram(chat_id, f"✅ 전체 {len(new_ones)}개 요약이 완료되었습니다!")

    except Exception as e:
        logger.exception("요약·전송 실패")
        await _send_telegram(chat_id, f"❌ 오류 발생: {e}")


async def _daily_job():
    """매일 6시 실행."""
    global _send_chat_id
    cid = _send_chat_id or TELEGRAM_CHAT_ID
    if not cid:
        logger.warning("TELEGRAM_CHAT_ID 미설정. 첫 메시지 후에만 전송됩니다.")
        return
    logger.info("일일 요약 전송 시작")
    await _do_summarize_and_send(cid)


async def _on_message(update, context):
    """텔레그램 메시지 수신 시 (요약해줘, /summary 등)."""
    global _send_chat_id
    chat_id = str(update.effective_chat.id)
    text = (update.message.text or "").strip().lower()

    if not _send_chat_id:
        _send_chat_id = chat_id
        logger.info("chat_id 저장: %s", chat_id)

    triggers = ("요약", "summary", "/summary", "/start", "start", "새 영상")
    if any(t in text for t in triggers):
        await update.message.reply_text("🔄 새 영상 요약을 시작합니다...")
        await _do_summarize_and_send(chat_id)


def main():
    if not TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN이 .env에 설정되지 않았습니다.")
        print("텔레그램 @BotFather 에서 봇을 만들고 토큰을 .env에 넣으세요.")
        sys.exit(1)

    from telegram.ext import Application, CommandHandler, MessageHandler, filters

    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(
        _daily_job,
        CronTrigger(hour=DAILY_HOUR, minute=DAILY_MINUTE),
        id="daily_summary",
    )

    async def post_init(application):
        scheduler.start()
        logger.info("매일 %s:%s (%s) 에 요약 전송 예약됨", DAILY_HOUR, DAILY_MINUTE, TIMEZONE)

    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )
    app.add_handler(MessageHandler(filters.TEXT, _on_message))
    app.add_handler(CommandHandler("summary", _on_message))
    app.add_handler(CommandHandler("start", _on_message))
    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
