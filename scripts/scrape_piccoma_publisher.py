#!/usr/bin/env python3
"""
픽코마 publisher/author/label 재수집 스크립트

- works 테이블에서 piccoma 플랫폼 중 publisher가 없는 작품을 조회
- 각 작품의 상세 페이지(https://piccoma.com/web/product/XXXXX)를 방문
- author, publisher, label 추출 후 DB 업데이트
- 2초 딜레이, 배치 처리, 20개마다 커밋 및 진행 상황 출력
"""

import asyncio
import logging
import sys
from pathlib import Path

# 프로젝트 루트 설정
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / '.env')

import psycopg2
from crawler.db import get_db_connection, save_work_detail

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(project_root / 'scripts' / 'scrape_piccoma_publisher.log', encoding='utf-8'),
    ]
)
logger = logging.getLogger(__name__)

DELAY_SECONDS = 2.0
BATCH_SIZE = 50  # Playwright context refresh interval
COMMIT_EVERY = 20  # DB commit interval


def get_piccoma_works_missing_publisher():
    """publisher가 없는 piccoma/piccoma_manga 작품 목록 조회"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT platform, title, url
        FROM works
        WHERE platform IN ('piccoma', 'piccoma_manga')
          AND (publisher IS NULL OR publisher = '')
          AND url IS NOT NULL
          AND url != ''
        ORDER BY platform, title
    """)
    rows = cursor.fetchall()
    conn.close()
    return [{'platform': r[0], 'title': r[1], 'url': r[2]} for r in rows]


async def scrape_piccoma_detail(page, url: str) -> dict:
    """
    픽코마 상세 페이지에서 author, publisher, label 추출.
    detail_scraper.py의 _scrape_piccoma와 동일한 셀렉터 사용.
    """
    await page.goto(url, wait_until='domcontentloaded', timeout=20000)

    detail = await page.evaluate('''
        () => {
            const result = {};

            // JSON-LD에서 Product 데이터 추출 (description, genre)
            const scripts = document.querySelectorAll('script[type="application/ld+json"]');
            for (const s of scripts) {
                try {
                    const data = JSON.parse(s.textContent);
                    if (data["@type"] === "Product") {
                        result.description = data.description || '';
                        if (data.offers && data.offers.category) {
                            result.genre = data.offers.category;
                        }
                    }
                } catch(e) {}
            }

            // 작가 (author) — 중복 제거
            const authorLinks = document.querySelectorAll('a[href*="/author/product/list/"]');
            if (authorLinks.length > 0) {
                result.author = [...new Set(Array.from(authorLinks).map(a => a.textContent.trim()))].join(', ');
            }

            // 출판사 (publisher/partner) — 중복 제거
            const partnerLinks = document.querySelectorAll('a[href*="/partner/product/list/"]');
            if (partnerLinks.length > 0) {
                result.publisher = [...new Set(Array.from(partnerLinks).map(a => a.textContent.trim()))].join(', ');
            }

            // 레이블 (category/label) — 중복 제거
            const categoryLinks = document.querySelectorAll('a[href*="/category/product/list/"]');
            if (categoryLinks.length > 0) {
                result.label = [...new Set(Array.from(categoryLinks).map(a => a.textContent.trim()))].join(', ');
            }

            // 하트수 (いいね)
            const likeImg = document.querySelector('img[alt="いいね"]');
            if (likeImg) {
                const parent = likeImg.closest('.PCM-productHome_like, [class*="like"]') || likeImg.parentElement;
                if (parent) {
                    const text = parent.textContent.replace(/[^0-9,]/g, '').replace(/,/g, '');
                    if (text) result.hearts = parseInt(text, 10);
                }
            }

            return result;
        }
    ''')

    return detail or {}


async def main():
    from playwright.async_api import async_playwright

    # 1) 대상 작품 조회
    works = get_piccoma_works_missing_publisher()
    total = len(works)
    logger.info(f"픽코마 publisher 미수집 작품: {total}개")

    if total == 0:
        logger.info("재수집 대상 없음. 종료.")
        return

    success = 0
    failed = 0
    skipped = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        # 배치 단위로 컨텍스트 갱신 (메모리 누수 방지)
        for batch_start in range(0, total, BATCH_SIZE):
            batch_end = min(batch_start + BATCH_SIZE, total)
            batch = works[batch_start:batch_end]
            logger.info(f"--- 배치 {batch_start+1}~{batch_end} / {total} ---")

            context = await browser.new_context(
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
            )
            page = await context.new_page()

            for i, work in enumerate(batch, batch_start + 1):
                platform = work['platform']
                title = work['title']
                url = work['url']

                try:
                    detail = await scrape_piccoma_detail(page, url)

                    has_publisher = bool(detail.get('publisher'))
                    has_author = bool(detail.get('author'))
                    has_label = bool(detail.get('label'))

                    if has_publisher or has_author or has_label:
                        save_work_detail(platform, title, detail)
                        success += 1
                        parts = []
                        if has_author:
                            parts.append(f"author={detail['author'][:30]}")
                        if has_publisher:
                            parts.append(f"pub={detail['publisher'][:30]}")
                        if has_label:
                            parts.append(f"label={detail['label'][:30]}")
                        info_str = ', '.join(parts)
                        if i <= 5 or i % 20 == 0 or i == total:
                            logger.info(f"  [{i}/{total}] OK: {title[:40]} => {info_str}")
                    else:
                        skipped += 1
                        if i <= 5 or i % 20 == 0:
                            logger.info(f"  [{i}/{total}] SKIP (no pub/author/label): {title[:40]}")

                except Exception as e:
                    failed += 1
                    logger.warning(f"  [{i}/{total}] FAIL: {title[:40]} - {e}")

                # 진행 상황 (20개마다)
                if i % 20 == 0:
                    logger.info(f"  === 진행: {i}/{total} (성공:{success}, 스킵:{skipped}, 실패:{failed}) ===")

                # 딜레이
                if i < total:
                    await asyncio.sleep(DELAY_SECONDS)

            await page.close()
            await context.close()
            logger.info(f"--- 배치 완료. 누적: 성공:{success}, 스킵:{skipped}, 실패:{failed} ---")

        await browser.close()

    logger.info("=" * 60)
    logger.info(f"픽코마 publisher/author/label 수집 완료")
    logger.info(f"  총 대상: {total}")
    logger.info(f"  수집 성공: {success}")
    logger.info(f"  데이터 없음 (스킵): {skipped}")
    logger.info(f"  실패: {failed}")
    logger.info("=" * 60)


if __name__ == '__main__':
    asyncio.run(main())
