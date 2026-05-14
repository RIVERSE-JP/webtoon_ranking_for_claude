#!/usr/bin/env python3
"""
title_kr 대량 채우기 (Google Translate 무료 API)

Claude API 크레딧 부족 시 대안으로 사용.
Google Translate로 일본어→한국어 번역 후 품질 검증.
"""

import os
import sys
import json
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from dotenv import load_dotenv
load_dotenv()

import psycopg2
from crawler.translator import translate_title, flush_mappings, is_translatable

DB_URL = os.environ['SUPABASE_DB_URL']
MAPPINGS_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'title_mappings.json')
BATCH_SIZE = 50  # Google Translate rate limit 고려


def get_missing_titles() -> list[str]:
    """DB에서 title_kr 누락 고유 제목 수집"""
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT title FROM works
        WHERE (title_kr IS NULL OR title_kr = '')
        ORDER BY title
    """)
    titles = [row[0] for row in cur.fetchall()]
    conn.close()
    return titles


def update_db(translations: dict[str, str]):
    """DB 업데이트 (works + rankings)"""
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    w_total = r_total = 0

    for jp, kr in translations.items():
        if not kr:
            continue
        cur.execute(
            "UPDATE works SET title_kr=%s WHERE title=%s AND (title_kr IS NULL OR title_kr='')",
            (kr, jp)
        )
        w_total += cur.rowcount
        cur.execute(
            "UPDATE rankings SET title_kr=%s WHERE title=%s AND (title_kr IS NULL OR title_kr='')",
            (kr, jp)
        )
        r_total += cur.rowcount

    conn.commit()
    conn.close()
    return w_total, r_total


def update_mappings(translations: dict[str, str]):
    """title_mappings.json 업데이트 (translator 모듈이 캐시 보유)"""
    flush_mappings()
    with open(MAPPINGS_PATH, 'r', encoding='utf-8') as f:
        mappings = json.load(f)
    return len(translations), len(mappings)


def main():
    print("=" * 60)
    print("title_kr 대량 채우기 (Google Translate)")
    print("=" * 60)

    missing = get_missing_titles()
    print(f"\n📊 누락: {len(missing)}개")

    if not missing:
        print("✅ 누락 없음!")
        return

    total_done = 0
    total_skip = 0
    batch_translations = {}

    for i, title in enumerate(missing):
        if not is_translatable(title):
            total_skip += 1
            continue
        kr = translate_title(title)

        if kr:
            batch_translations[title] = kr
            total_done += 1
        else:
            total_skip += 1

        # 배치 저장 (50개마다)
        if len(batch_translations) >= BATCH_SIZE or i == len(missing) - 1:
            if batch_translations:
                w, r = update_db(batch_translations)
                added, total_maps = update_mappings(batch_translations)
                batch_num = (i // BATCH_SIZE) + 1
                print(f"  ✅ 배치 {batch_num}: {len(batch_translations)}개 번역 / DB: w{w} r{r} / 매핑: +{added} (총 {total_maps})")
                batch_translations = {}

        # rate limit 방지 (5개마다 0.5초)
        if (i + 1) % 5 == 0:
            time.sleep(0.5)

        # 진행 상황 (500개마다)
        if (i + 1) % 500 == 0:
            print(f"  📈 진행: {i+1}/{len(missing)} (번역: {total_done}, 스킵: {total_skip})")

    # rankings 추가 크로스레퍼런스
    print("\n🔄 rankings 추가 크로스레퍼런스...")
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute('''
        UPDATE rankings r1
        SET title_kr = (
            SELECT r2.title_kr FROM rankings r2
            WHERE r2.title = r1.title AND r2.title_kr IS NOT NULL AND r2.title_kr != ''
            LIMIT 1
        )
        WHERE (r1.title_kr IS NULL OR r1.title_kr = '')
        AND EXISTS (
            SELECT 1 FROM rankings r2
            WHERE r2.title = r1.title AND r2.title_kr IS NOT NULL AND r2.title_kr != ''
        )
    ''')
    extra = cur.rowcount
    conn.commit()

    # 최종 현황
    cur.execute("SELECT COUNT(*) FROM works WHERE (title_kr IS NULL OR title_kr = '')")
    w_remain = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM rankings WHERE (title_kr IS NULL OR title_kr = '')")
    r_remain = cur.fetchone()[0]
    conn.close()

    print(f"\n{'=' * 60}")
    print(f"✅ 완료!")
    print(f"   번역 성공: {total_done}개")
    print(f"   품질 검증 실패: {total_skip}개")
    print(f"   rankings 추가 복구: {extra}행")
    print(f"   남은 빈 title_kr: works {w_remain}개, rankings {r_remain}개")


if __name__ == "__main__":
    main()
