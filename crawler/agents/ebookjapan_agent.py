"""
이북재팬 (ebookjapan / Yahoo) 크롤러 에이전트

URL 구조 (2026년 기준):
- 종합 랭킹: /ranking/details/?page=N  (페이지당 50위, page=3은 101~150위 등 최대 5+페이지)
- 소녀/여성: /ranking/details/?genre=womens&page=N
- 소년/청년: /ranking/details/?genre=mens&page=N
- 판타지:    /ranking/details/?tag=112&page=N
- BL:       /ranking/details/?genre=bl&page=N
- TL:       /ranking/details/?genre=tl&page=N

랭킹 단위 주의:
사이트의 raw 랭킹은 "단행본(권)" 단위라 같은 시리즈가 여러 권 동시 등장.
크롤러는 시리즈명만 추출(권 번호 제거)하여 중복 제거 → 시리즈 기준 인기 100작품 수집.
페이지 1,2만으로는 중복 때문에 100개 미달이라, 최대 MAX_PAGES까지 페이지를 늘려서 채움.

주의: /ranking/ 최상위 페이지는 카테고리별 3개만 표시하므로 사용하지 않음
"""

import re
from typing import List, Dict, Any
from playwright.async_api import Browser

from crawler.agents.base_agent import CrawlerAgent


class EbookjapanAgent(CrawlerAgent):
    """이북재팬 일간 랭킹 크롤러 에이전트"""

    GENRE_RANKINGS = {
        '': {'name': '종합', 'base_url': 'https://ebookjapan.yahoo.co.jp/ranking/details/'},
        '少女・女性': {'name': '소녀/여성', 'base_url': 'https://ebookjapan.yahoo.co.jp/ranking/details/?genre=womens'},
        '少年・青年': {'name': '소년/청년', 'base_url': 'https://ebookjapan.yahoo.co.jp/ranking/details/?genre=mens'},
        'ファンタジー': {'name': '판타지', 'base_url': 'https://ebookjapan.yahoo.co.jp/ranking/details/?tag=112'},
        'BL': {'name': 'BL', 'base_url': 'https://ebookjapan.yahoo.co.jp/ranking/details/?genre=bl'},
        'TL': {'name': 'TL', 'base_url': 'https://ebookjapan.yahoo.co.jp/ranking/details/?genre=tl'},
    }

    def __init__(self):
        super().__init__(
            platform_id='ebookjapan',
            platform_name='이북재팬 (ebookjapan)',
            url='https://ebookjapan.yahoo.co.jp/ranking/details/'
        )
        self.genre_results = {}

    def _build_page_url(self, base_url: str, page: int) -> str:
        """페이지 URL 생성"""
        if '?' in base_url:
            return f"{base_url}&page={page}"
        else:
            return f"{base_url}?page={page}"

    TARGET_RANK = 100   # 카테고리당 목표 작품 수 (시리즈 기준)
    MAX_PAGES = 5       # 안전 상한 (페이지당 50개 × 5 = 최대 250 단행본 탐색)

    async def crawl(self, browser: Browser) -> List[Dict[str, Any]]:
        """이북재팬 종합 + 카테고리별 랭킹 크롤링

        시리즈 기준 100작품을 모을 때까지 페이지 1→2→3...순으로 진행.
        100개 도달 시 즉시 중단, MAX_PAGES까지 가도 미달이면 그대로 종료.
        """
        page = await browser.new_page()
        all_rankings = []

        try:
            for genre_key, genre_info in self.GENRE_RANKINGS.items():
                label = genre_info['name']
                base_url = genre_info['base_url']

                self.logger.info(f"📱 이북재팬 [{label}] 크롤링 중...")

                try:
                    genre_rankings = []
                    seen_titles = set()  # 시리즈 중복 제거

                    for page_num in range(1, self.MAX_PAGES + 1):
                        if len(genre_rankings) >= self.TARGET_RANK:
                            break

                        page_url = self._build_page_url(base_url, page_num)
                        self.logger.info(f"   페이지 {page_num}: {page_url}")

                        await page.goto(page_url, wait_until='domcontentloaded', timeout=20000)
                        await page.wait_for_timeout(3000)

                        # 팝업 닫기
                        try:
                            close_btn = await page.query_selector('button:has-text("閉じる")')
                            if close_btn:
                                await close_btn.click()
                                await page.wait_for_timeout(1000)
                        except Exception:
                            pass

                        # 스크롤로 lazy loading 트리거 (페이지 3+도 50개 다 로드되려면 20회 필요)
                        for _ in range(20):
                            await page.evaluate('window.scrollBy(0, 800)')
                            await page.wait_for_timeout(400)

                        items = await self._parse_page_items(page, genre_key)

                        added = 0
                        for it in items:
                            if len(genre_rankings) >= self.TARGET_RANK:
                                break
                            title = it['title']
                            if title in seen_titles:
                                continue
                            seen_titles.add(title)
                            it['rank'] = len(genre_rankings) + 1  # 시리즈 기준 재번호
                            genre_rankings.append(it)
                            added += 1

                        self.logger.info(
                            f"   페이지 {page_num}: {len(items)}개 중 신규 {added}개 (누계 {len(genre_rankings)}/{self.TARGET_RANK})"
                        )

                    self.logger.info(f"   ✅ [{label}]: {len(genre_rankings)}개 작품")

                    self.genre_results[genre_key] = genre_rankings
                    if genre_key == '':
                        all_rankings = genre_rankings

                except Exception as e:
                    self.logger.warning(f"   ⚠️ [{label}] 크롤링 실패: {e}")
                    self.genre_results[genre_key] = []
                    continue

            return all_rankings

        finally:
            await page.close()

    async def _parse_page_items(self, page, genre_key: str) -> List[Dict[str, Any]]:
        """한 페이지에서 작품 추출 (rank 부여/중복 제거는 호출자가 담당)"""
        items = await page.evaluate("""() => {
            const results = [];
            const imgs = document.querySelectorAll('img.cover-main__img');

            for (const img of imgs) {
                const src = img.getAttribute('src') || '';
                if (!src.startsWith('http') || src.includes('loading-book-cover')) continue;

                let alt = img.getAttribute('alt') || '';
                if (!alt || alt.length < 2) continue;

                // 권수/레이블/판형 패턴 제거
                let title = alt
                    .replace(/[\\s　]+（[０-９0-9]+）（[^）]+）$/u, '')  // （8）（ガルドコミックス）
                    .replace(/[\\s　]*（[０-９0-9]+）$/u, '')           // （8）
                    .replace(/[\\s　]+[０-９]+$/u, '')                  // 전각 숫자
                    .replace(/[\\s　]+\\d+巻?$/, '')                    // N巻 or N
                    .replace(/[\\s　]*[:：][\\s　]*\\d*$/, '')          // ：N or trailing ：
                    .replace(/\\d+【[^】]*】$/, '')                     // 16【電子特典付き】
                    .replace(/【[^】]*】$/, '')                         // 【電子限定特典付き】
                    .replace(/【[^】]*】/g, '')                         // 중간의 【通常版】等
                    .replace(/[\\s　]+\\d+号.*$/, '')                   // 13号 [2026年...]
                    .replace(/\\s*\\[\\d{4}年.*$/, '')                   // [2026年2月25日発売]
                    .replace(/[\\s　]+第[０-９0-9]+巻$/, '')            // 第５巻
                    .replace(/[\\s　]+\\d+$/, '')                       // trailing number
                    .trim();
                if (!title || title.length < 2) continue;

                // URL 추출
                const container = img.closest('li') || img.closest('div') || img.parentElement;
                const linkEl = container ? container.querySelector('a[href*="/books/"]') || container.querySelector('a') : null;
                const href = linkEl ? linkEl.getAttribute('href') : '';
                const fullUrl = href ? (href.startsWith('http') ? href : 'https://ebookjapan.yahoo.co.jp' + href) : '';

                results.push({
                    title: title,
                    url: fullUrl,
                    thumbnail_url: src,
                });
            }
            return results;
        }""")

        # rank는 호출자가 부여 — 여기선 페이지에서 추출한 그대로 반환
        return [
            {
                'title': item['title'],
                'genre': genre_key if genre_key else '総合',
                'url': item.get('url', ''),
                'thumbnail_url': item.get('thumbnail_url', ''),
            }
            for item in items[:50]
        ]

    async def save(self, date: str, data: List[Dict[str, Any]]):
        """종합 + 장르별 랭킹 모두 저장"""
        from crawler.db import save_rankings, backup_to_json, save_works_metadata

        save_rankings(date, self.platform_id, data, sub_category='')
        works_meta = [
            {'title': item['title'], 'thumbnail_url': item.get('thumbnail_url', ''),
             'url': item.get('url', ''), 'genre': item.get('genre', ''), 'rank': item.get('rank')}
            for item in data if item.get('thumbnail_url')
        ]
        if works_meta:
            save_works_metadata(self.platform_id, works_meta, date=date, sub_category='')
        backup_to_json(date, self.platform_id, data)

        for genre_key, rankings in self.genre_results.items():
            if genre_key == '':
                continue
            genre_name = self.GENRE_RANKINGS[genre_key]['name']
            save_rankings(date, self.platform_id, rankings, sub_category=genre_key)
            genre_meta = [
                {'title': item['title'], 'thumbnail_url': item.get('thumbnail_url', ''),
                 'url': item.get('url', ''), 'genre': item.get('genre', ''), 'rank': item.get('rank')}
                for item in rankings if item.get('thumbnail_url')
            ]
            if genre_meta:
                save_works_metadata(self.platform_id, genre_meta, date=date, sub_category=genre_key)
            self.logger.info(f"   💾 [{genre_name}]: {len(rankings)}개 저장")
