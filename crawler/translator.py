"""
신작 자동 번역 모듈 (일/영 → 한)
- Google Translate (deep-translator) 사용, API key 불필요
- title_mappings.json 영구 캐시
- validate_title_kr 통과한 결과만 캐시에 저장
- 가짜 제목(숫자/프로모션 텍스트) 사전 차단
"""

import atexit
import json
import re
import threading
import time
from pathlib import Path
from typing import Optional

from deep_translator import GoogleTranslator

from .utils import (
    project_root,
    load_title_mappings,
    validate_title_kr,
)


_LOCK = threading.Lock()
_MAPPINGS_PATH = project_root / 'data' / 'title_mappings.json'

_GARBAGE_RE = re.compile(r'^[0-9,]+(\.[0-9]+)?(万|千)?$')
_TOO_SHORT_RE = re.compile(r'^.{1,2}$')
_KR_HANGUL_RE = re.compile(r'[\uAC00-\uD7AF]')

_translator: Optional[GoogleTranslator] = None
_failure_log: set = set()
_dirty = False
_pending_writes = 0


def _get_translator() -> GoogleTranslator:
    global _translator
    if _translator is None:
        _translator = GoogleTranslator(source='auto', target='ko')
    return _translator


def is_translatable(title: str) -> bool:
    """번역 시도할 가치가 있는 제목인지 사전 필터."""
    if not title or not title.strip():
        return False
    if _GARBAGE_RE.match(title.strip()):
        return False
    if _TOO_SHORT_RE.match(title.strip()):
        return False
    if _KR_HANGUL_RE.search(title):
        return False
    return True


def translate_title(jp_or_en_title: str, retry: int = 2) -> str:
    """
    원제 → 한국어 번역. 실패 시 빈 문자열.
    캐시(title_mappings.json) 우선, miss 시 Google Translate 호출.
    """
    if not is_translatable(jp_or_en_title):
        return ""

    mappings = load_title_mappings()
    cached = mappings.get(jp_or_en_title)
    if cached:
        validated = validate_title_kr(cached, jp_or_en_title)
        if validated:
            return validated

    if jp_or_en_title in _failure_log:
        return ""

    try:
        translator = _get_translator()
        result = None
        for attempt in range(retry + 1):
            try:
                result = translator.translate(jp_or_en_title)
                break
            except Exception:
                if attempt < retry:
                    time.sleep(1.0 * (attempt + 1))
                else:
                    raise
        if not result:
            _failure_log.add(jp_or_en_title)
            return ""
        validated = validate_title_kr(result, jp_or_en_title)
        if not validated:
            _failure_log.add(jp_or_en_title)
            return ""
        _store_mapping(jp_or_en_title, validated)
        return validated
    except Exception:
        _failure_log.add(jp_or_en_title)
        return ""


def _store_mapping(src: str, kr: str) -> None:
    """매핑을 메모리 캐시에 추가. 디스크 flush는 batch로."""
    global _dirty, _pending_writes
    mappings = load_title_mappings()
    if mappings.get(src) == kr:
        return
    with _LOCK:
        mappings[src] = kr
        _dirty = True
        _pending_writes += 1
        # 50건마다 자동 flush
        if _pending_writes >= 50:
            _flush_locked()


def _flush_locked() -> None:
    """잠금 보유 상태에서 디스크 flush."""
    global _dirty, _pending_writes
    if not _dirty:
        return
    mappings = load_title_mappings()
    tmp_path = _MAPPINGS_PATH.with_suffix('.json.tmp')
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(mappings, f, ensure_ascii=False, indent=2, sort_keys=True)
    tmp_path.replace(_MAPPINGS_PATH)
    _dirty = False
    _pending_writes = 0


def flush_mappings() -> None:
    """디스크 flush 명시 호출 (크롤러 종료 시 등)."""
    with _LOCK:
        _flush_locked()


def get_failure_report() -> set:
    return _failure_log.copy()


atexit.register(flush_mappings)
