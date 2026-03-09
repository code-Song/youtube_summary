/**
 * YouTube 구독 채널 ID 추출 스크립트
 *
 * 사용법:
 * 1. https://www.youtube.com/feed/channels 접속 (로그인 필수)
 * 2. F12 → Console 탭
 * 3. 이 스크립트 전체 복사 후 붙여넣기 실행
 * 4. 스크롤이 끝날 때까지 대기 (구독이 많으면 1~2분)
 * 5. 출력된 채널 ID를 복사
 * 6. 터미널에서: python fetch_subscriptions.py --from-js
 *    그 다음 채널 ID 붙여넣기 후 Ctrl+Z (Windows) / Ctrl+D (Mac/Linux)
 */
(function() {
  function getLast() {
    try {
      const data = ytInitialData?.contents?.twoColumnBrowseResultsRenderer?.tabs?.[0]?.tabRenderer?.content?.sectionListRenderer?.contents;
      return data ? data.slice(-1)[0] : null;
    } catch (e) { return null; }
  }

  function canContinue() {
    const last = getLast();
    return last && last.continuationItemRenderer != null;
  }

  async function loadAll() {
    while (canContinue()) {
      const current = getLast().continuationItemRenderer.continuationEndpoint.continuationCommand.token;
      scrollTo(0, document.getElementById('primary')?.scrollHeight || document.body.scrollHeight);
      while (canContinue() && current === getLast().continuationItemRenderer.continuationEndpoint.continuationCommand.token) {
        await new Promise(r => setTimeout(r, 150));
      }
    }
  }

  function extractChannelIds() {
    const contents = ytInitialData?.contents?.twoColumnBrowseResultsRenderer?.tabs?.[0]?.tabRenderer?.content?.sectionListRenderer?.contents || [];
    const ids = [];
    for (const section of contents) {
      if (!section.itemSectionRenderer) continue;
      const items = section.itemSectionRenderer?.contents?.[0]?.shelfRenderer?.content?.expandedShelfContentsRenderer?.items || [];
      for (const item of items) {
        const ch = item?.channelRenderer;
        if (ch?.channelId) ids.push(ch.channelId);
      }
    }
    return ids;
  }

  (async () => {
    console.log('구독 채널 로딩 중... 스크롤 완료될 때까지 대기');
    await loadAll();
    scrollTo(0, 0);

    const ids = extractChannelIds();
    const text = ids.join('\n');
    console.log('=== 채널 ID (아래 전체 복사) ===');
    console.log(text);
    console.log('=== 끝 ===');

    const div = document.createElement('div');
    div.style.cssText = 'position:fixed;inset:1rem;background:#1a1a1a;z-index:99999;overflow:auto;padding:1rem;font-family:monospace;white-space:pre;color:#0f0;border:2px solid #0f0;';
    const btn = document.createElement('button');
    btn.textContent = '클립보드 복사';
    btn.onclick = () => { navigator.clipboard.writeText(text); alert('복사됨'); };
    div.appendChild(document.createTextNode('채널 ID ' + ids.length + '개\n\n' + text));
    div.appendChild(btn);
    document.body.appendChild(div);
  })();
})();
