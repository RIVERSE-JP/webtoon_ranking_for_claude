"""
cmoa (コミックシーモア) 상세 페이지에서 출판사/저자/레이블 정보 스크래핑

대상: works 테이블에서 publisher가 비어있고, 오늘 랭킹에 있는 cmoa 작품
"""

import asyncio
import sys
import os
import re
from pathlib import Path
from datetime import datetime

# 프로젝트 루트 설정
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / '.env')

import psycopg2
from playwright.async_api import async_playwright

DATABASE_URL = os.environ.get('SUPABASE_DB_URL', '')
TODAY = datetime.now().strftime('%Y-%m-%d')


def get_works_missing_publisher():
    """오늘 랭킹에 있는 cmoa 작품 중 publisher가 비어있는 것들 조회"""
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT w.title, w.url
        FROM works w
        INNER JOIN rankings r ON r.platform = w.platform AND r.title = w.title
        WHERE w.platform = 'cmoa'
          AND (w.publisher IS NULL OR w.publisher = '')
          AND w.url IS NOT NULL AND w.url != ''
          AND r.date = %s
        ORDER BY w.title
    """, (TODAY,))
    rows = cur.fetchall()
    conn.close()
    return rows


def update_work(title: str, publisher: str, author: str, label: str):
    """works 테이블 업데이트"""
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    sets = []
    vals = []
    if publisher:
        sets.append("publisher = %s")
        vals.append(publisher)
    if author:
        sets.append("author = %s")
        vals.append(author)
    if label:
        sets.append("label = %s")
        vals.append(label)

    if not sets:
        conn.close()
        return False

    vals.extend(['cmoa', title])
    sql = f"UPDATE works SET {', '.join(sets)} WHERE platform = %s AND title = %s"
    cur.execute(sql, vals)
    updated = cur.rowcount
    conn.commit()
    conn.close()
    return updated > 0


async def scrape_detail_page(page, url: str) -> dict:
    """
    cmoa 상세 페이지에서 출판사/저자/레이ベル 정보 추출

    cmoa 상세 페이지 구조 예시:
    - 著者: <dt>著者</dt><dd>作者名</dd>
    - 出版社: <dt>出版社</dt><dd>出版社名</dd>
    - レーベル: <dt>レーベル</dt><dd>レーベル名</dd>
    """
    result = {'publisher': '', 'author': '', 'label': ''}

    try:
        await page.goto(url, wait_until='domcontentloaded', timeout=20000)
        await page.wait_for_timeout(1500)

        # 方法1: dt/dd ペア (일반적인 cmoa 구조)
        html = await page.content()

        # 出版社 (publisher)
        m = re.search(r'<dt[^>]*>\s*出版社\s*</dt>\s*<dd[^>]*>(.*?)</dd>', html, re.DOTALL)
        if m:
            text = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            if text:
                result['publisher'] = text

        # レーベル (label)
        m = re.search(r'<dt[^>]*>\s*レーベル\s*</dt>\s*<dd[^>]*>(.*?)</dd>', html, re.DOTALL)
        if m:
            text = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            if text:
                result['label'] = text

        # 著者/作者 (author)
        m = re.search(r'<dt[^>]*>\s*(?:著者|作者|著)\s*</dt>\s*<dd[^>]*>(.*?)</dd>', html, re.DOTALL)
        if m:
            text = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            if text:
                result['author'] = text

        # 方法2: fallback - .title_detail_info or similar selectors
        if not result['publisher'] and not result['author']:
            # Try alternative selectors
            for selector in ['.title_detail_info', '.title_detail', '#detail_info', '.detail_info']:
                el = await page.query_selector(selector)
                if el:
                    inner = await el.inner_html()

                    if not result['publisher']:
                        m = re.search(r'出版社[：:]\s*([^<\n]+)', inner)
                        if m:
                            result['publisher'] = m.group(1).strip()

                    if not result['label']:
                        m = re.search(r'レーベル[：:]\s*([^<\n]+)', inner)
                        if m:
                            result['label'] = m.group(1).strip()

                    if not result['author']:
                        m = re.search(r'(?:著者|作者|著)[：:]\s*([^<\n]+)', inner)
                        if m:
                            result['author'] = m.group(1).strip()
                    break

        # 方法3: もう1つのfallback - ページ全体のテキストからパターン検索
        if not result['publisher'] and not result['author']:
            # search_result_box_right_sec2 내의 저자 정보
            author_els = await page.query_selector_all('a[href*="/author/"]')
            if author_els:
                names = []
                for el in author_els[:3]:  # 최대 3명
                    name = (await el.inner_text()).strip()
                    if name and name not in names:
                        names.append(name)
                if names:
                    result['author'] = ' / '.join(names)

            # publisher link
            pub_els = await page.query_selector_all('a[href*="/publisher/"]')
            if pub_els:
                result['publisher'] = (await pub_els[0].inner_text()).strip()

            # label link
            label_els = await page.query_selector_all('a[href*="/label/"]')
            if label_els:
                result['label'] = (await label_els[0].inner_text()).strip()

    except Exception as e:
        print(f"    [ERROR] 페이지 스크래핑 실패: {e}")

    # Clean author field
    result['author'] = clean_author(result['author'])
    return result


def clean_author(author: str) -> str:
    """もっと見る (see more button text) 등 불필요한 텍스트 제거"""
    if not author:
        return ''
    # Remove "もっと見る" entries
    parts = [p.strip() for p in author.split('/')]
    parts = [p for p in parts if p and p != 'もっと見る']
    return ' / '.join(parts)


def fix_existing_authors():
    """이미 저장된 author에서 もっと見る 제거"""
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("""
        SELECT title, author FROM works
        WHERE platform = 'cmoa' AND author LIKE '%%もっと見る%%'
    """)
    rows = cur.fetchall()
    print(f"\n=== もっと見る 클리닝: {len(rows)}개 대상 ===")
    for title, author in rows:
        cleaned = clean_author(author)
        if cleaned != author:
            cur.execute("UPDATE works SET author = %s WHERE platform = 'cmoa' AND title = %s",
                        (cleaned, title))
    conn.commit()
    print(f"클리닝 완료: {len(rows)}개 수정")
    conn.close()


async def main():
    print(f"=== cmoa 출판사 정보 스크래핑 ({TODAY}) ===\n")

    # 1. 대상 작품 조회
    works = get_works_missing_publisher()
    print(f"대상 작품: {len(works)}개 (오늘 랭킹에 있고 publisher 비어있는 cmoa 작품)\n")

    if not works:
        print("처리할 작품이 없습니다.")
        return

    # 2. Playwright로 스크래핑
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(ignore_https_errors=True)
        page = await context.new_page()

        success_count = 0
        skip_count = 0
        error_count = 0
        batch_updates = []

        for i, (title, url) in enumerate(works):
            print(f"[{i+1}/{len(works)}] {title[:50]}")
            print(f"    URL: {url}")

            try:
                info = await scrape_detail_page(page, url)

                publisher = info.get('publisher', '')
                author = info.get('author', '')
                label = info.get('label', '')

                if publisher or author or label:
                    print(f"    -> 출판사: {publisher or '(없음)'}")
                    print(f"    -> 저자: {author or '(없음)'}")
                    print(f"    -> 레이블: {label or '(없음)'}")

                    updated = update_work(title, publisher, author, label)
                    if updated:
                        success_count += 1
                        print(f"    [OK] DB 업데이트 완료")
                    else:
                        skip_count += 1
                        print(f"    [SKIP] DB 업데이트 실패 (행 없음?)")
                else:
                    skip_count += 1
                    print(f"    [SKIP] 정보 없음")

            except Exception as e:
                error_count += 1
                print(f"    [ERROR] {e}")

            # 진행률 출력 (20개마다)
            if (i + 1) % 20 == 0:
                print(f"\n--- 진행: {i+1}/{len(works)} (성공: {success_count}, 스킵: {skip_count}, 에러: {error_count}) ---\n")

        await page.close()
        await context.close()
        await browser.close()

    # 3. 결과 요약
    print(f"\n{'='*60}")
    print(f"=== 완료 ===")
    print(f"전체: {len(works)}개")
    print(f"성공: {success_count}개")
    print(f"스킵: {skip_count}개")
    print(f"에러: {error_count}개")
    print(f"{'='*60}")


if __name__ == '__main__':
    # まず既存データのクリーニング
    fix_existing_authors()
    # 新規スクレイピング
    asyncio.run(main())
