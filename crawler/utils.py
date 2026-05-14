"""
공통 유틸리티 함수
- 제목 매핑 (일본어 → 한국어)
- 리버스 작품 판별
- 장르 번역
"""

import json
import os
import re
import time
from pathlib import Path
from typing import Optional


# 프로젝트 루트
project_root = Path(__file__).parent.parent


# 장르 번역 딕셔너리 (일본어 → 한국어)
GENRE_TRANSLATIONS = {
    # 픽코마 장르
    'ファンタジー': '판타지',
    '恋愛': '연애',
    'アクション': '액션',
    'ドラマ': '드라마',
    'ホラー': '호러',
    'ミステリー': '미스터리',
    'スポーツ': '스포츠',
    'グルメ': '요리',
    '日常': '일상',
    'TL': 'TL',
    'BL': 'BL',
    '裏社会': '뒷세계',
    'アングラ': '언더그라운드',
    'ホラー・ミステリー': '호러/미스터리',
    '裏社会・アングラ': '뒷세계/언더그라운드',

    # 일반 장르
    'コメディ': '코미디',
    'サスペンス': '서스펜스',
    'SF': 'SF',
    'ヒューマンドラマ': '휴먼드라마',
    '学園': '학원',
    '恋愛ドラマ': '연애드라마',
    'ハートフル': '훈훈',
    '復讐': '복수',
    '異世界': '이세계',
    '転生': '전생',
    '冒険': '모험',
    'バトル': '배틀',
    '格闘': '격투',
    '歴史': '역사',
    '時代劇': '시대극',
    '推理': '추리',
    '探偵': '탐정',
    'サバイバル': '서바이벌',
    'ゾンビ': '좀비',
    '医療': '의료',
    '料理': '요리',
    '音楽': '음악',
    '芸能': '연예',
    'ビジネス': '비즈니스',
    'お仕事': '직업',
    '家族': '가족',
    '友情': '우정',
    '青春': '청춘',
    '成長': '성장',
    '職業': '직업',
    '日常系': '일상계',
    '癒し': '힐링',
    '感動': '감동',
    '泣ける': '눈물',
    'ギャグ': '개그',
    'ラブコメ': '러브코미디',
}


# 참조 데이터 로드 (지연 로딩)
_riverse_titles = None
_title_mappings = None


def load_riverse_titles() -> dict:
    """리버스 작품 목록 로드 (캐싱)"""
    global _riverse_titles

    if _riverse_titles is None:
        try:
            path = project_root / 'data' / 'riverse_titles.json'
            with open(path, 'r', encoding='utf-8') as f:
                _riverse_titles = json.load(f)
            print(f"✅ 리버스 작품 {len(_riverse_titles)}개 로드")
        except FileNotFoundError:
            print(f"⚠️  riverse_titles.json 파일이 없습니다. 빈 딕셔너리 사용")
            _riverse_titles = {}
        except json.JSONDecodeError:
            print(f"❌ riverse_titles.json 파싱 실패. 빈 딕셔너리 사용")
            _riverse_titles = {}

    return _riverse_titles


def load_title_mappings() -> dict:
    """한국어 제목 매핑 로드 (캐싱)"""
    global _title_mappings

    if _title_mappings is None:
        try:
            path = project_root / 'data' / 'title_mappings.json'
            with open(path, 'r', encoding='utf-8') as f:
                _title_mappings = json.load(f)
            print(f"✅ 한국어 제목 {len(_title_mappings)}개 로드")
        except FileNotFoundError:
            print(f"⚠️  title_mappings.json 파일이 없습니다. 빈 딕셔너리 사용")
            _title_mappings = {}
        except json.JSONDecodeError:
            print(f"❌ title_mappings.json 파싱 실패. 빈 딕셔너리 사용")
            _title_mappings = {}

    return _title_mappings


# ─── title_kr 품질 검증 ──────────────────────────────────────
_JP_KANA_RE = re.compile(r'[\u3041-\u3096\u30A1-\u30F6]')       # 히라가나+카타카나
_KR_HANGUL_RE = re.compile(r'[\uAC00-\uD7AF\u3131-\u3163]')     # 한글 음절+자모
_PHONETIC_RE = re.compile(
    r'타치|라레|테모|세루|테오다|키타|나테이타|시테|사레|마시타|데스'
)
_JUNK_KEY_RE = re.compile(r'^\d+位$|^[\d.]+万$')
_PROMO_KEYWORDS = ['巻分無料', '割引セール', '割引', '無料増', 'ポイント還元']

_bad_title_kr_log: set = set()


def validate_title_kr(title_kr: str, source_key: str = '') -> str:
    """
    title_kr 품질 검증. 불량이면 빈 문자열 반환.

    Rules:
    1. source_key가 비제목(순위/숫자/프로모션) → ""
    2. value에 히라가나/카타카나 포함 → "" (미번역)
    3. value에 한글 없고 4자 이상 → "" (번역 안 됨)
    4. 음역 패턴 + source가 일본어 → "" (기계적 음역)
    """
    if not title_kr or not title_kr.strip():
        return ""

    # Rule 1: junk key
    if source_key:
        if _JUNK_KEY_RE.match(source_key):
            _bad_title_kr_log.add(source_key)
            return ""
        if any(kw in source_key for kw in _PROMO_KEYWORDS):
            _bad_title_kr_log.add(source_key)
            return ""

    # Rule 2: 히라가나/카타카나 in value → bad
    if _JP_KANA_RE.search(title_kr):
        _bad_title_kr_log.add(source_key or title_kr)
        return ""

    # Rule 3: 한글 없고 4자 이상 + source가 일본어 → bad (번역 안 된 것)
    if (not _KR_HANGUL_RE.search(title_kr) and len(title_kr) >= 4
            and source_key and _JP_KANA_RE.search(source_key)):
        _bad_title_kr_log.add(source_key or title_kr)
        return ""

    # Rule 4: 음역 패턴 + 일본어 원본 → bad
    if source_key and _JP_KANA_RE.search(source_key) and _PHONETIC_RE.search(title_kr):
        _bad_title_kr_log.add(source_key)
        return ""

    return title_kr


def get_bad_title_kr_report() -> set:
    """세션 중 거부된 title_kr 키 목록"""
    return _bad_title_kr_log.copy()


def clear_bad_title_kr_report():
    """거부 로그 초기화"""
    _bad_title_kr_log.clear()


def get_korean_title(jp_title: str) -> str:
    """
    제목 → 한국어 제목 매핑 (일본어 + 영어 지원)

    Args:
        jp_title: 일본어 또는 영어 제목

    Returns:
        한국어 제목 (없으면 빈 문자열)
    """
    if not jp_title:
        return ""

    riverse = load_riverse_titles()
    mappings = load_title_mappings()

    # 1순위: 정확한 매칭 (리버스 작품)
    if jp_title in riverse:
        return riverse[jp_title]

    # 2순위: 정확한 매칭 (일반 매핑) — 품질 검증 적용
    if jp_title in mappings:
        return validate_title_kr(mappings[jp_title], jp_title)

    # 3순위: 대소문자 무시 매칭 (영어 제목용)
    title_lower = jp_title.lower()
    for key, kr in riverse.items():
        if key.lower() == title_lower:
            return kr
    for key, kr in mappings.items():
        if key.lower() == title_lower:
            return validate_title_kr(kr, key)

    # 4순위: 대괄호 제거 후 매칭 (【】, [], ())
    cleaned = jp_title
    for bracket in ['【', '】', '[', ']', '(', ')']:
        cleaned = cleaned.replace(bracket, '')

    if cleaned != jp_title:
        if cleaned in riverse:
            return riverse[cleaned]
        if cleaned in mappings:
            return validate_title_kr(mappings[cleaned], cleaned)

    # 5순위: 부분 매칭 (4글자 이상)
    if len(jp_title) >= 4:
        for jp, kr in riverse.items():
            if len(jp) >= 4 and jp in jp_title:
                return kr

        for jp, kr in mappings.items():
            if len(jp) >= 4 and jp in jp_title:
                return validate_title_kr(kr, jp)

    # 6순위: 자동 번역 fallback (Google Translate, 캐시됨)
    # 환경변수 DISABLE_AUTO_TRANSLATE=1 로 끌 수 있음
    if os.getenv('DISABLE_AUTO_TRANSLATE') != '1':
        try:
            from .translator import translate_title
            return translate_title(jp_title)
        except Exception:
            pass

    return ""


def is_riverse_title(jp_title: str) -> bool:
    """
    리버스 작품 여부 판별

    Args:
        jp_title: 일본어/영어 제목

    Returns:
        True: 리버스 작품, False: 일반 작품
    """
    if not jp_title:
        return False

    riverse = load_riverse_titles()

    # 정확한 매칭
    if jp_title in riverse:
        return True

    # 대괄호 제거 후 매칭
    cleaned = jp_title
    for bracket in ['【', '】', '[', ']', '(', ')']:
        cleaned = cleaned.replace(bracket, '')

    if cleaned in riverse:
        return True

    # 부분 매칭 (4글자 이상)
    if len(jp_title) >= 4:
        for jp in riverse.keys():
            if len(jp) >= 4 and jp in jp_title:
                return True

    # 한국어 제목 역체크 (영어 제목 → 한국어 매핑 → 리버스 목록 확인)
    kr_title = get_korean_title(jp_title)
    if kr_title:
        kr_base = kr_title.split('[')[0].split('(')[0].strip()
        riverse_kr = set()
        for kr in riverse.values():
            riverse_kr.add(kr)
            riverse_kr.add(kr.split('[')[0].split('(')[0].strip())
        if kr_title in riverse_kr or kr_base in riverse_kr:
            return True

    return False


def translate_genre(jp_genre: str) -> str:
    """
    일본어 장르 → 한국어 번역

    Args:
        jp_genre: 일본어 장르 (예: "ファンタジー" 또는 "ファンタジー / アクション")

    Returns:
        한국어 장르 (없으면 원문 그대로)
    """
    if not jp_genre:
        return ""

    # 복합 장르 처리 (예: "ファンタジー / アクション")
    if ' / ' in jp_genre or '/' in jp_genre:
        # "/" 또는 " / "로 분리
        separator = ' / ' if ' / ' in jp_genre else '/'
        genres = jp_genre.split(separator)
        translated = []

        for genre in genres:
            genre = genre.strip()
            if genre in GENRE_TRANSLATIONS:
                translated.append(GENRE_TRANSLATIONS[genre])
            else:
                # 부분 매칭 시도
                found = False
                for jp, kr in GENRE_TRANSLATIONS.items():
                    if jp in genre:
                        translated.append(kr)
                        found = True
                        break
                if not found:
                    translated.append(genre)  # 원문 유지

        return ' / '.join(translated)

    # 단일 장르
    jp_genre = jp_genre.strip()

    # 정확한 매칭
    if jp_genre in GENRE_TRANSLATIONS:
        return GENRE_TRANSLATIONS[jp_genre]

    # 부분 매칭
    for jp, kr in GENRE_TRANSLATIONS.items():
        if jp in jp_genre:
            return kr

    # 매칭 실패 - 원문 그대로
    return jp_genre


def _extract_json(text: str) -> dict:
    """응답 텍스트에서 JSON 객체 추출 (robust)"""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0].strip()
    start = text.find("{")
    if start == -1:
        return {}
    depth = 0
    for i in range(start, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i+1])
                except json.JSONDecodeError:
                    break
    return {}


def fill_missing_title_kr():
    """
    크롤링 후 title_kr 누락 작품 자동 번역.
    1. DB에서 title_kr 빈 고유 제목 수집
    2. 기존 매핑으로 복구 가능한 것 먼저 적용
    3. 나머지는 Claude API로 배치 번역
    4. title_mappings.json + DB(works, rankings) 업데이트
    """
    try:
        from deep_translator import GoogleTranslator
    except ImportError:
        print("⚠️  deep-translator 패키지 없음 — pip install deep-translator --break-system-packages")
        return

    from dotenv import load_dotenv
    load_dotenv(project_root / '.env')

    db_url = os.environ.get('SUPABASE_DB_URL', '')
    if not db_url:
        print("⚠️  DB URL 없음 — 자동 번역 건너뜀")
        return

    import psycopg2

    # 1. DB에서 title_kr 누락 제목 수집
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT title FROM works
        WHERE (title_kr IS NULL OR title_kr = '')
        ORDER BY title
    """)
    missing = [row[0] for row in cur.fetchall()]
    conn.close()

    if not missing:
        print("✅ title_kr 누락 없음")
        return

    print(f"\n🔤 title_kr 누락: {len(missing)}개")

    # 2. 기존 매핑으로 복구
    mappings = load_title_mappings()
    already_mapped = {}
    still_missing = []
    for t in missing:
        kr = get_korean_title(t)
        if kr:
            already_mapped[t] = kr
        else:
            still_missing.append(t)

    if already_mapped:
        print(f"  🔄 기존 매핑 복구: {len(already_mapped)}개")
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        for jp, kr in already_mapped.items():
            cur.execute("UPDATE works SET title_kr=%s WHERE title=%s AND (title_kr IS NULL OR title_kr='')", (kr, jp))
            cur.execute("UPDATE rankings SET title_kr=%s WHERE title=%s AND (title_kr IS NULL OR title_kr='')", (kr, jp))
        conn.commit()
        conn.close()

    if not still_missing:
        print("✅ 모든 title_kr 복구 완료")
        return

    print(f"  🌐 Google Translate 번역 필요: {len(still_missing)}개")

    # 3. GoogleTranslator 개별 번역 (매 배치 후 즉시 저장)
    translator = GoogleTranslator(source='ja', target='ko')
    BATCH = 50
    total_translated = 0
    mappings_path = project_root / 'data' / 'title_mappings.json'

    for i in range(0, len(still_missing), BATCH):
        batch = still_missing[i:i+BATCH]
        result = {}

        for jp in batch:
            for retry in range(3):
                try:
                    kr = translator.translate(jp)
                    if kr:
                        result[jp] = kr
                    break
                except Exception as e:
                    print(f"  ⚠️  번역 오류 (재시도 {retry+1}/3): {jp[:30]} — {e}")
                    time.sleep(2)

        # 번역 결과 품질 검증
        validated = {}
        for jp, kr in result.items():
            if not kr:
                continue
            if validate_title_kr(kr, jp):
                validated[jp] = kr
            else:
                print(f"  ⚠️  번역 불량 스킵: {jp} → {kr[:30]}")

        # 즉시 DB 저장
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        w_count = r_count = 0
        for jp, kr in validated.items():
            cur.execute("UPDATE works SET title_kr=%s WHERE title=%s AND (title_kr IS NULL OR title_kr='')", (kr, jp))
            w_count += cur.rowcount
            cur.execute("UPDATE rankings SET title_kr=%s WHERE title=%s AND (title_kr IS NULL OR title_kr='')", (kr, jp))
            r_count += cur.rowcount
        conn.commit()
        conn.close()

        # 즉시 매핑 JSON 저장
        with open(mappings_path, 'r', encoding='utf-8') as f:
            current_mappings = json.load(f)
        added = 0
        for jp, kr in validated.items():
            if jp not in current_mappings:
                current_mappings[jp] = kr
                added += 1
        sorted_m = dict(sorted(current_mappings.items()))
        with open(mappings_path, 'w', encoding='utf-8') as f:
            json.dump(sorted_m, f, ensure_ascii=False, indent=2)

        total_translated += len(validated)
        skipped = len(result) - len(validated)
        skip_msg = f" / 불량 스킵: {skipped}" if skipped else ""
        print(f"  ✅ 배치 {i//BATCH+1}: {len(validated)}개 번역 / DB: w{w_count} r{r_count} / 매핑: +{added}{skip_msg}")

        if i + BATCH < len(still_missing):
            time.sleep(1)

    # 매핑 캐시 무효화
    global _title_mappings
    _title_mappings = None

    # 세션 중 거부된 불량 title_kr 보고
    bad_report = get_bad_title_kr_report()
    if bad_report:
        print(f"  ⚠️  불량 title_kr {len(bad_report)}개 거부됨 (매핑 불량 → 빈값 처리)")
        for key in sorted(bad_report)[:10]:
            print(f"     {key}")
        if len(bad_report) > 10:
            print(f"     ... 외 {len(bad_report) - 10}개")
    clear_bad_title_kr_report()

    print(f"  📊 총 {total_translated}개 번역 완료")


if __name__ == "__main__":
    # 테스트
    print("=" * 60)
    print("유틸리티 함수 테스트")
    print("=" * 60)

    # 장르 번역 테스트
    print("\n[장르 번역 테스트]")
    test_genres = [
        'ファンタジー',
        '恋愛',
        'ファンタジー / アクション',
        'ホラー・ミステリー',
        '알 수 없는 장르'
    ]
    for genre in test_genres:
        print(f"  {genre} → {translate_genre(genre)}")

    # 리버스 판별 테스트
    print("\n[리버스 작품 판별 테스트]")
    riverse = load_riverse_titles()
    if riverse:
        sample_titles = list(riverse.keys())[:3]
        for title in sample_titles:
            kr = get_korean_title(title)
            is_rv = is_riverse_title(title)
            print(f"  {title}")
            print(f"    → 한국어: {kr}")
            print(f"    → 리버스: {is_rv}")
    else:
        print("  ⚠️  리버스 작품 데이터 없음")

    print("\n" + "=" * 60)
    print("테스트 완료")
    print("=" * 60)
