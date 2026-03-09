# -*- coding: utf-8 -*-
"""영상 자막 추출 + LLM 요약."""
from __future__ import annotations

from typing import Callable, Coroutine, Optional

from youtube_fetcher import VideoInfo


def get_transcript(video_id: str) -> Optional[str]:
    """자막 추출. 자막 없으면 None."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound
        try:
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
        except (TranscriptsDisabled, NoTranscriptFound):
            return None
        text = " ".join(t["text"] for t in transcript_list)
        return text.strip() if text else None
    except ImportError:
        return None


async def summarize_with_gemini_stream(
    text: str,
    title: str,
    on_chunk: Callable[[str], Coroutine],
    max_chars: int = 12000,
) -> str:
    """
    Gemini 스트리밍 요약.
    청크(토큰)가 생성될 때마다 on_chunk(chunk_text) 콜백을 호출합니다.
    최종 완성된 전체 요약문을 반환합니다.
    """
    import asyncio
    import google.generativeai as genai
    from config import GEMINI_API_KEY, GEMINI_MODEL

    if not GEMINI_API_KEY:
        msg = "(Gemini API 키가 없어 요약을 건너뜁니다.)"
        await on_chunk(msg)
        return msg

    if len(text) > max_chars:
        text = text[:max_chars] + "\n[...중략...]"

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(GEMINI_MODEL)
    prompt = f"""당신은 영상 자막을 읽고 3~5문장으로 핵심만 간결하게 요약하는 도우미입니다. 한국어로 답변하세요.

제목: {title}

자막:
{text}"""

    full_text = ""
    loop = asyncio.get_running_loop()

    # Gemini stream은 동기 generator → executor로 비동기 처리
    def _call_stream():
        return model.generate_content(
            prompt,
            stream=True,
            generation_config=genai.types.GenerationConfig(max_output_tokens=500),
        )

    response = await loop.run_in_executor(None, _call_stream)

    for chunk in response:
        part = chunk.text or ""
        if part:
            full_text += part
            await on_chunk(part)

    return full_text.strip() if full_text else "(요약 생성 실패)"


def summarize_video(video: VideoInfo) -> tuple[str, bool]:
    """
    영상 요약 (동기 버전, 스케줄러 등 non-async 용도).
    자막 없으면 제목만으로 짧은 설명 반환.
    """
    transcript = get_transcript(video.video_id)
    if not transcript:
        return f"제목: {video.title}\n(자막 없음 - 제목만으로는 요약 불가)", False

    import google.generativeai as genai
    from config import GEMINI_API_KEY, GEMINI_MODEL

    if not GEMINI_API_KEY:
        return "(Gemini API 키가 없어 요약을 건너뜁니다.)", False

    if len(transcript) > 12000:
        transcript = transcript[:12000] + "\n[...중략...]"

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(GEMINI_MODEL)
    prompt = f"""당신은 영상 자막을 읽고 3~5문장으로 핵심만 간결하게 요약하는 도우미입니다. 한국어로 답변하세요.

제목: {video.title}

자막:
{transcript}"""
    resp = model.generate_content(
        prompt,
        generation_config=genai.types.GenerationConfig(max_output_tokens=500),
    )
    summary = resp.text.strip() if resp.text else "(요약 생성 실패)"
    return summary, True
