# -*- coding: utf-8 -*-
"""
구독 유튜버 새 영상 요약 서비스
- 매일 아침 6시 요약 전송
- 텔레그램에서 "요약해줘" 등 메시지 보내면 즉시 요약 전송 (스트리밍)
- HF Spaces: Webhook 방식 (Polling 대신)
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).parent))

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, Request
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

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

# ── 환경변수 ──────────────────────────────────────────────────────────
# HF Spaces에서는 SPACE_HOST 환경변수가 자동으로 설정됨
# 예: codeSong-youtube-summary.hf.space
SPACE_HOST = os.environ.get("SPACE_HOST", "")
WEBHOOK_URL = f"https://{SPACE_HOST}/webhook" if SPACE_HOST else ""
PORT = int(os.environ.get("PORT", "7860"))

# 전역: 보낼 chat_id
_send_chat_id: str | None = TELEGRAM_CHAT_ID or None

# ── FastAPI 앱 및 Telegram Application ───────────────────────────────
fastapi_app = FastAPI()
ptb_app: Application | None = None


async def _send_telegram(chat_id: str, text: str):
    """텔레그램으로 메시지 전송 (4096자 제한 처리)."""
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    for i in range(0, len(text), 4096):
        await bot.send_message(chat_id=chat_id, text=text[i:i + 4096])


async def _do_summarize_and_send(chat_id: str):
    """새 영상 조회 → 스트리밍 요약 → 실시간 텔레그램 전송."""
    bot = Bot(token=TELEGRAM_BOT_TOKEN)

    try:
        videos = get_new_videos()
        new_ones = [v for v in videos if not is_seen(v.video_id)]
        if not new_ones:
            await _send_telegram(chat_id, "🆕 오늘 새 영상이 없습니다.")
            return

        await _send_telegram(chat_id, f"🔍 새 영상 {len(new_ones)}개를 요약합니다...")

        for idx, video in enumerate(new_ones, 1):
            header = (
                f"📺 [{idx}/{len(new_ones)}] {video.channel_title}\n"
                f"제목: {video.title}\n"
                f"{video.url}\n\n"
                f"📝 요약 중..."
            )
            sent = await bot.send_message(chat_id=chat_id, text=header)
            msg_id = sent.message_id

            transcript = get_transcript(video.video_id)

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

            accumulated = ""
            last_sent_len = 0

            async def on_chunk(part: str, _msg_id=msg_id, _idx=idx, _video=video):
                nonlocal accumulated, last_sent_len
                accumulated += part
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
                        pass

            try:
                summary = await summarize_with_gemini_stream(
                    transcript, video.title, on_chunk
                )
                mark_seen(video.video_id, video.channel_id, video.channel_title, video.title)
            except Exception as e:
                logger.exception("요약 실패: %s", video.video_id)
                summary = f"(요약 실패: {e})"
                mark_seen(video.video_id, video.channel_id, video.channel_title, video.title)

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


async def _on_message(update: Update, context):
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


# ── FastAPI 엔드포인트 ────────────────────────────────────────────────

@fastapi_app.get("/")
async def health_check():
    """HF Spaces 헬스체크 / 상태 확인."""
    return {"status": "ok", "webhook": WEBHOOK_URL or "not set"}


@fastapi_app.post("/webhook")
async def telegram_webhook(request: Request):
    """Telegram이 보내는 업데이트를 수신."""
    if ptb_app is None:
        return {"ok": False, "error": "bot not initialized"}
    data = await request.json()
    update = Update.de_json(data, ptb_app.bot)
    await ptb_app.process_update(update)
    return {"ok": True}


# ── 앱 시작/종료 이벤트 ───────────────────────────────────────────────

@fastapi_app.on_event("startup")
async def on_startup():
    """서버 시작 시: Telegram 봇 초기화 + Webhook 등록 + 스케줄러 시작."""
    global ptb_app

    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN이 설정되지 않았습니다!")
        return

    # PTB Application 빌드
    ptb_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    ptb_app.add_handler(MessageHandler(filters.TEXT, _on_message))
    ptb_app.add_handler(CommandHandler("summary", _on_message))
    ptb_app.add_handler(CommandHandler("start", _on_message))

    await ptb_app.initialize()

    # Webhook 등록
    if WEBHOOK_URL:
        await ptb_app.bot.set_webhook(url=WEBHOOK_URL)
        logger.info("Webhook 등록 완료: %s", WEBHOOK_URL)
    else:
        logger.warning(
            "SPACE_HOST 환경변수 미설정 → Webhook URL을 알 수 없습니다. "
            "HF Spaces Secrets에 SPACE_HOST를 설정하거나 "
            "자동으로 설정될 때까지 기다리세요."
        )

    # 스케줄러 시작
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(
        _daily_job,
        CronTrigger(hour=DAILY_HOUR, minute=DAILY_MINUTE),
        id="daily_summary",
    )
    scheduler.start()
    logger.info("매일 %s:%s (%s) 에 요약 전송 예약됨", DAILY_HOUR, DAILY_MINUTE, TIMEZONE)


@fastapi_app.on_event("shutdown")
async def on_shutdown():
    """서버 종료 시: Webhook 해제."""
    if ptb_app:
        await ptb_app.bot.delete_webhook()
        await ptb_app.shutdown()
        logger.info("Webhook 해제 완료")


# ── 직접 실행 시 (로컬 테스트용) ─────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(fastapi_app, host="0.0.0.0", port=PORT)
