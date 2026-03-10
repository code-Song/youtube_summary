# -*- coding: utf-8 -*-
"""
구독 유튜버 새 영상 요약 서비스
- 매일 아침 6시 요약 전송
- 텔레그램 Webhook 방식 (HF Spaces 호환)
- startup 시 네트워크 호출 없이 FastAPI 먼저 기동 후 백그라운드에서 봇 초기화
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, Request
from telegram import Bot, Update

from config import (
    DAILY_HOUR,
    DAILY_MINUTE,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    TIMEZONE,
)
from storage import is_seen, mark_seen
from summarizer import get_transcript, summarize_with_gemini_stream
from youtube_fetcher import get_new_videos

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ── 환경변수 ──────────────────────────────────────────────────────────
SPACE_HOST = os.environ.get("SPACE_HOST", "")
WEBHOOK_URL = f"https://{SPACE_HOST}/webhook" if SPACE_HOST else ""
PORT = int(os.environ.get("PORT", "7860"))

# 전역
_send_chat_id: str | None = TELEGRAM_CHAT_ID or None
_bot: Bot | None = None           # 지연 초기화
_bot_ready = False                 # 봇 초기화 완료 여부

fastapi_app = FastAPI()


# ── 텔레그램 메시지 전송 ─────────────────────────────────────────────

async def _send_telegram(chat_id: str, text: str):
    """텔레그램으로 메시지 전송 (4096자 제한 처리)."""
    if not _bot:
        logger.warning("봇 미초기화 상태에서 전송 시도")
        return
    for i in range(0, len(text), 4096):
        await _bot.send_message(chat_id=chat_id, text=text[i:i + 4096])


async def _do_summarize_and_send(chat_id: str):
    """새 영상 조회 → 스트리밍 요약 → 실시간 텔레그램 전송."""
    if not _bot:
        return
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
            sent = await _bot.send_message(chat_id=chat_id, text=header)
            msg_id = sent.message_id

            transcript = get_transcript(video.video_id)

            if not transcript:
                no_sub = (
                    f"📺 [{idx}/{len(new_ones)}] {video.channel_title}\n"
                    f"제목: {video.title}\n"
                    f"{video.url}\n\n"
                    f"⚠️ 자막 없음 - 요약 불가"
                )
                await _bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=no_sub)
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
                        await _bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=_msg_id,
                            text=preview[:4096],
                        )
                        last_sent_len = len(accumulated)
                    except Exception:
                        pass

            try:
                summary = await summarize_with_gemini_stream(transcript, video.title, on_chunk)
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
                await _bot.edit_message_text(
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
    cid = _send_chat_id or TELEGRAM_CHAT_ID
    if not cid:
        logger.warning("TELEGRAM_CHAT_ID 미설정.")
        return
    logger.info("일일 요약 전송 시작")
    await _do_summarize_and_send(cid)


async def _handle_update(update: Update):
    """수신된 Telegram 업데이트 처리."""
    global _send_chat_id

    if not update.message or not update.message.text:
        return

    chat_id = str(update.effective_chat.id)
    text = update.message.text.strip().lower()

    if not _send_chat_id:
        _send_chat_id = chat_id
        logger.info("chat_id 저장: %s", chat_id)

    triggers = ("요약", "summary", "/summary", "/start", "start", "새 영상")
    if any(t in text for t in triggers):
        await _bot.send_message(chat_id=chat_id, text="🔄 새 영상 요약을 시작합니다...")
        await _do_summarize_and_send(chat_id)


# ── 백그라운드: 봇 초기화 + Webhook 등록 (재시도 포함) ────────────────

async def _init_bot_with_retry():
    """
    FastAPI 기동 후 백그라운드에서 Telegram 봇 초기화.
    네트워크가 준비될 때까지 최대 10회 재시도 (간격: 30초).
    """
    global _bot, _bot_ready

    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN이 설정되지 않았습니다!")
        return

    # Bot 객체 생성 (네트워크 호출 없음)
    _bot = Bot(token=TELEGRAM_BOT_TOKEN)

    # 초기 대기 (컨테이너 네트워크 완전 초기화 대기)
    await asyncio.sleep(5)

    for attempt in range(1, 11):
        try:
            # get_me()로 봇 토큰 검증 (네트워크 필요)
            me = await _bot.get_me()
            logger.info("봇 초기화 성공: @%s", me.username)
            _bot_ready = True

            # Webhook 등록
            if WEBHOOK_URL:
                await _bot.set_webhook(url=WEBHOOK_URL)
                logger.info("Webhook 등록 완료: %s", WEBHOOK_URL)
            else:
                logger.warning(
                    "SPACE_HOST 미설정 → Webhook URL 불명. "
                    "/setup-webhook 엔드포인트를 통해 수동 등록하세요."
                )
            return

        except Exception as e:
            logger.warning(
                "봇 초기화 시도 %d/10 실패: %s. 30초 후 재시도...", attempt, e
            )
            await asyncio.sleep(30)

    logger.error("봇 초기화 10회 모두 실패. 네트워크 환경을 확인하세요.")


# ── FastAPI 엔드포인트 ────────────────────────────────────────────────

@fastapi_app.get("/")
async def health_check():
    """헬스체크 / 상태 확인."""
    return {
        "status": "ok",
        "bot_ready": _bot_ready,
        "webhook_url": WEBHOOK_URL or "not set",
    }


@fastapi_app.get("/setup-webhook")
async def setup_webhook():
    """수동으로 Webhook 등록 (SPACE_HOST 환경변수 설정 후 호출)."""
    if not _bot:
        return {"ok": False, "error": "봇 미초기화"}
    if not WEBHOOK_URL:
        return {"ok": False, "error": "SPACE_HOST 환경변수 미설정"}
    try:
        result = await _bot.set_webhook(url=WEBHOOK_URL)
        info = await _bot.get_webhook_info()
        return {"ok": result, "webhook_url": WEBHOOK_URL, "info": str(info)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@fastapi_app.post("/webhook")
async def telegram_webhook(request: Request):
    """Telegram이 보내는 업데이트 수신."""
    if not _bot:
        logger.warning("봇 미준비 상태에서 webhook 수신")
        return {"ok": False, "error": "bot not ready"}
    try:
        data = await request.json()
        update = Update.de_json(data, _bot)
        asyncio.create_task(_handle_update(update))
    except Exception as e:
        logger.exception("webhook 처리 오류: %s", e)
    return {"ok": True}


# ── FastAPI 시작/종료 이벤트 ──────────────────────────────────────────

@fastapi_app.on_event("startup")
async def on_startup():
    """
    ★ 핵심: startup에서는 네트워크 호출을 하지 않음.
    - 스케줄러만 시작
    - Telegram 봇 초기화는 백그라운드 태스크로 처리
    """
    # 스케줄러 시작 (네트워크 불필요)
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(
        _daily_job,
        CronTrigger(hour=DAILY_HOUR, minute=DAILY_MINUTE),
        id="daily_summary",
    )
    scheduler.start()
    logger.info("스케줄러 시작: 매일 %s:%s (%s)", DAILY_HOUR, DAILY_MINUTE, TIMEZONE)

    # Telegram 봇 초기화는 백그라운드에서 (startup 블로킹 없음)
    asyncio.create_task(_init_bot_with_retry())
    logger.info("FastAPI 기동 완료. Telegram 봇 초기화 백그라운드 진행 중...")


@fastapi_app.on_event("shutdown")
async def on_shutdown():
    """종료 시 Webhook 해제."""
    if _bot and _bot_ready:
        try:
            await _bot.delete_webhook()
            logger.info("Webhook 해제 완료")
        except Exception as e:
            logger.warning("Webhook 해제 실패: %s", e)


# ── 로컬 실행 ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(fastapi_app, host="0.0.0.0", port=PORT)
