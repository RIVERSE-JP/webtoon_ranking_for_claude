#!/usr/bin/env python3
"""
works / rankings 의 비어 있는 publisher / genre / genre_kr 백필 스크립트.

이미 DB에 저장된 값만 전파한다 (외부 조회/번역 API 호출 없음).
- 소스 1순위: 같은 unified_work_id 의 unified_works 값
- 소스 2순위: 같은 unified_work_id 로 연결된 다른 works(형제) 레코드의 값
- rankings 는 (platform, title) 정확 일치하는 works 의 유효값(works→unified 순)으로
  비어 있는 genre / genre_kr 만 채운다.

안전 정책:
- 기본은 dry-run. --apply 를 명시해야만 실제 UPDATE (단일 트랜잭션).
- 링크 검증: works.title_kr 과 unified_works.title_kr 이 둘 다 존재하고 정확히
  같은 연결만 verified. 불일치(mismatch)/검증불가(unverifiable) 연결은 전파 대상에서
  제외하고 통계만 출력한다. 형제 후보도 verified 형제만 사용한다.
- 모든 필드(publisher / genre / genre_kr): 후보가 서로 다르면(충돌) 자동 적용하지 않는다.
- genre / genre_kr 은 채우려는 값(과 기존 값)이 모순 없이 맞는 단일 소스가
  존재할 때만 채운다 (서로 다른 소스의 장르쌍 섞기 방지).
- 비어 있지 않은 값(공백만 있는 문자열 제외)은 절대 덮어쓰지 않는다.
  UPDATE 도 PK(id) 기반 + CASE WHEN col IS NULL OR TRIM(col)='' 로 이중 보호
  (기존 비어 있지 않은 값은 공백조차 수정하지 않음).
- 동시변경 차단: UPDATE WHERE 에 계획 당시 값을 재검증한다.
  rankings 는 id + platform + title, works 는 id + unified_work_id +
  title_kr(trim exact). 계획 후 행이 바뀌었으면 UPDATE 가 매치되지 않고
  commit 전 검증에서 잡힌다.
- --apply 시 commit 전에 PK 기준으로 계획값 반영 여부를 검증하고, 적용 후
  누락 집계까지 같은 트랜잭션에서 실행한다. 어느 단계든 실패하면
  예외 → rollback (commit 은 모든 검증·집계 성공 후에만).

사용:
  python3 scripts/backfill_work_metadata.py                     # dry-run (기본)
  python3 scripts/backfill_work_metadata.py --rankings-scope all
  python3 scripts/backfill_work_metadata.py --apply             # 실제 적용
"""
import argparse
import sys
from collections import defaultdict
from pathlib import Path

WORK_FIELDS = ('publisher', 'genre', 'genre_kr')
RANKING_FIELDS = ('genre', 'genre_kr')
GENRE_PAIR = ('genre', 'genre_kr')


# ---------------------------------------------------------------------------
# 순수 함수 (DB 불필요 — 단위테스트 대상)
# ---------------------------------------------------------------------------

def clean(value):
    """공백 제거 후 비어 있으면 None, 아니면 정리된 문자열."""
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def link_status(work, unified):
    """
    work → unified_works 연결의 검증 상태.

    - 'unlinked': unified_work_id 없음 또는 unified 레코드 없음
    - 'unverifiable': 어느 한쪽의 title_kr 이 비어 있어 검증 불가
    - 'mismatch': 양쪽 title_kr 이 있으나 서로 다름 (오연결 의심)
    - 'verified': 양쪽 title_kr 이 존재하고 정확히 같음
    """
    if work.get('unified_work_id') is None or unified is None:
        return 'unlinked'
    wk = clean(work.get('title_kr'))
    uk = clean(unified.get('title_kr'))
    if wk is None or uk is None:
        return 'unverifiable'
    return 'verified' if wk == uk else 'mismatch'


def resolve_field(current, candidate_values):
    """
    한 필드의 백필 값을 보수적으로 결정한다.

    Returns (new_value_or_None, has_conflict).
    - current 가 비어 있지 않으면 (None, False): 절대 덮어쓰지 않음.
    - 후보(빈 값 제외)가 정확히 1가지 값일 때만 채운다.
    - 서로 다른 후보가 2개 이상이면 충돌 → 채우지 않음 (모든 필드 공통).
    """
    if clean(current) is not None:
        return None, False
    distinct = {v for v in (clean(c) for c in candidate_values) if v is not None}
    if not distinct:
        return None, False
    if len(distinct) == 1:
        return next(iter(distinct)), False
    return None, True


def genre_fill_compatible(set_fields, current_row, sources):
    """
    채우려는 genre/genre_kr 값이 하나의 소스와 모순 없이 맞는지 확인 (소스 섞기 방지).

    허용 조건: 채우려는 모든 장르 필드 값을 그대로 가진 소스가 존재하고,
    그 소스의 나머지 장르 필드도 현재 행의 기존 값과 모순되지 않아야 한다
    (소스가 그 필드를 비워 뒀으면 모순 아님).
    """
    target = {f: set_fields[f] for f in GENRE_PAIR if f in set_fields}
    if not target:
        return True
    for s in sources:
        ok = True
        for f in GENRE_PAIR:
            have = clean(s.get(f))
            if f in target:
                if have != target[f]:
                    ok = False
                    break
            else:
                existing = clean(current_row.get(f))
                if existing is not None and have is not None and have != existing:
                    ok = False
                    break
        if ok:
            return True
    return False


def plan_work_updates(works, unified_map):
    """
    works 백필 계획을 만든다. verified 연결만 전파 대상이며,
    형제 후보도 verified 형제만 사용한다.

    works: [{'id','platform','title','unified_work_id','title_kr',
             'publisher','genre','genre_kr'}, ...]
    unified_map: {unified_work_id: {'title_kr','publisher','genre','genre_kr'}}

    Returns (updates, stats)
      updates: [{'id','platform','title','unified_work_id','title_kr',
                 'set': {field: value}}, ...]
      (title_kr 는 trim 된 계획 당시 값 — UPDATE WHERE 재검증용)
      stats: {'filled': {f:n}, 'conflicts': {f:n}, 'pair_mix_skipped': n,
              'links': {'verified','mismatch','unverifiable','unlinked'}}
    """
    verified_by_unified = defaultdict(list)
    statuses = {}
    for w in works:
        st = link_status(w, unified_map.get(w.get('unified_work_id')))
        statuses[id(w)] = st
        if st == 'verified':
            verified_by_unified[w['unified_work_id']].append(w)

    updates = []
    stats = {
        'filled': {f: 0 for f in WORK_FIELDS},
        'conflicts': {f: 0 for f in WORK_FIELDS},
        'pair_mix_skipped': 0,
        'links': {'verified': 0, 'mismatch': 0, 'unverifiable': 0, 'unlinked': 0},
    }

    for w in works:
        st = statuses[id(w)]
        stats['links'][st] += 1
        if st != 'verified':
            continue  # mismatch / unverifiable / unlinked 는 전파 제외

        uid = w['unified_work_id']
        sources = [unified_map[uid]] + [
            s for s in verified_by_unified[uid] if s is not w
        ]
        set_fields = {}
        for f in WORK_FIELDS:
            value, conflict = resolve_field(w.get(f), [s.get(f) for s in sources])
            if conflict:
                stats['conflicts'][f] += 1
            if value is not None:
                set_fields[f] = value

        # 장르 필드는 모순 없는 단일 소스에서만 채운다 (소스 섞기 방지)
        if not genre_fill_compatible(set_fields, w, sources):
            for f in GENRE_PAIR:
                set_fields.pop(f, None)
            stats['pair_mix_skipped'] += 1

        for f in set_fields:
            stats['filled'][f] += 1
        if set_fields:
            updates.append({
                'id': w['id'], 'platform': w['platform'], 'title': w['title'],
                'unified_work_id': uid, 'title_kr': clean(w['title_kr']),
                'set': set_fields,
            })

    return updates, stats


def effective_work_meta(works, unified_map):
    """
    rankings 백필용 (platform, title) → {genre, genre_kr} 유효값 맵.

    장르쌍은 단일 소스에서만 가져온다:
    - works 에 genre/genre_kr 중 하나라도 있으면 works 값만 사용 (부분값 그대로).
    - works 에 둘 다 없으면 verified 연결된 unified_works 의 쌍을 사용.
    """
    meta = {}
    for w in works:
        entry = {f: clean(w.get(f)) for f in RANKING_FIELDS}
        entry = {f: v for f, v in entry.items() if v is not None}
        if not entry:
            unified = unified_map.get(w.get('unified_work_id'))
            if link_status(w, unified) == 'verified':
                entry = {f: clean(unified.get(f)) for f in RANKING_FIELDS}
                entry = {f: v for f, v in entry.items() if v is not None}
        if entry:
            meta[(w['platform'], w['title'])] = entry
    return meta


def plan_ranking_updates(rankings, works_meta):
    """
    rankings 백필 계획.

    rankings: [{'id','date','platform','sub_category','rank','title',
                'genre','genre_kr'}, ...]
    works_meta: effective_work_meta() 결과

    한 필드만 비어 있고 다른 필드의 기존 값이 소스의 값과 다르면(충돌 쌍)
    채우지 않는다 — 서로 다른 소스의 장르쌍이 한 행에 섞이는 것을 방지.

    Returns (updates, stats)
      updates: [{'id','platform','title','set': {field: value}}, ...]
      stats: {'filled': {f:n}, 'no_source': n, 'pair_conflicts': n}
    """
    updates = []
    stats = {'filled': {f: 0 for f in RANKING_FIELDS}, 'no_source': 0,
             'pair_conflicts': 0}

    for r in rankings:
        missing = [f for f in RANKING_FIELDS if clean(r.get(f)) is None]
        if not missing:
            continue
        meta = works_meta.get((r['platform'], r['title']))
        if not meta or not any(f in meta for f in missing):
            stats['no_source'] += 1
            continue

        # 기존 값이 있는 필드가 소스 값과 다르면 이 소스의 쌍을 섞지 않는다
        existing_conflicts = any(
            f not in missing and f in meta and clean(r.get(f)) != meta[f]
            for f in RANKING_FIELDS
        )
        if existing_conflicts:
            stats['pair_conflicts'] += 1
            continue

        set_fields = {f: meta[f] for f in missing if f in meta}
        for f in set_fields:
            stats['filled'][f] += 1
        updates.append({
            'id': r['id'], 'platform': r['platform'], 'title': r['title'],
            'set': set_fields,
        })

    return updates, stats


def _case_set_sql(fields):
    """비어 있는 경우에만 채우는 SET 절 (기존 비어 있지 않은 값은 공백조차 불변)."""
    return ', '.join(
        f"{f} = CASE WHEN {f} IS NULL OR TRIM({f}) = '' THEN %s ELSE {f} END"
        for f in fields
    )


def build_work_update_sql(fields):
    """
    works UPDATE SQL: PK(id) 기반 + 계획 당시 unified_work_id / title_kr 재검증.
    title_kr 는 양쪽 trim 후 정확 일치해야 한다 (파라미터는 trim 된 계획값).
    계획 후 행이 바뀌었으면 매치되지 않아 동시변경이 차단된다.
    """
    return (
        f"UPDATE works SET {_case_set_sql(fields)}, updated_at = NOW() "
        f"WHERE id = %s AND unified_work_id = %s AND TRIM(title_kr) = %s"
    )


def build_work_update_params(fields, update):
    """build_work_update_sql 의 placeholder 순서에 맞는 파라미터 튜플."""
    return tuple(update['set'][f] for f in fields) + (
        update['id'], update['unified_work_id'], update['title_kr'],
    )


def build_ranking_update_sql(fields):
    """
    rankings UPDATE SQL: PK(id) 기반 + 계획 당시 platform / title 재검증
    + 대상 필드가 여전히 비어 있는 조건. 계획 후 행이 바뀌었으면 매치되지 않는다.
    """
    still_empty = ' OR '.join(
        f"({f} IS NULL OR TRIM({f}) = '')" for f in fields
    )
    return (
        f"UPDATE rankings SET {_case_set_sql(fields)} "
        f"WHERE id = %s AND platform = %s AND title = %s AND ({still_empty})"
    )


def build_ranking_update_params(fields, update):
    """build_ranking_update_sql 의 placeholder 순서에 맞는 파라미터 튜플."""
    return tuple(update['set'][f] for f in fields) + (
        update['id'], update['platform'], update['title'],
    )


# ---------------------------------------------------------------------------
# DB 접근 (main 에서만)
# ---------------------------------------------------------------------------

def get_connection():
    import psycopg2
    from dotenv import load_dotenv
    import os
    project_root = Path(__file__).resolve().parent.parent
    load_dotenv(project_root / '.env')
    db_url = os.environ.get('SUPABASE_DB_URL', '')
    if not db_url:
        print('ERROR: SUPABASE_DB_URL 이 설정되어 있지 않습니다 (.env 확인).')
        sys.exit(1)
    return psycopg2.connect(db_url)


def fetch_missing_counts(cur, rankings_where, rankings_params):
    counts = {}
    for f in WORK_FIELDS:
        cur.execute(
            f"SELECT COUNT(*) FROM works WHERE {f} IS NULL OR TRIM({f}) = ''"
        )
        counts[f'works.{f}'] = cur.fetchone()[0]
    for f in RANKING_FIELDS:
        cur.execute(
            f"SELECT COUNT(*) FROM rankings WHERE ({f} IS NULL OR TRIM({f}) = '') AND {rankings_where}",
            rankings_params,
        )
        counts[f'rankings.{f}'] = cur.fetchone()[0]
    return counts


def apply_work_updates(cur, updates):
    from psycopg2.extras import execute_batch
    grouped = defaultdict(list)
    for u in updates:
        grouped[tuple(sorted(u['set']))].append(u)
    for fields, rows in grouped.items():
        sql = build_work_update_sql(fields)
        params = [build_work_update_params(fields, u) for u in rows]
        execute_batch(cur, sql, params, page_size=200)


def apply_ranking_updates(cur, updates):
    from psycopg2.extras import execute_batch
    grouped = defaultdict(list)
    for u in updates:
        grouped[tuple(sorted(u['set']))].append(u)
    for fields, rows in grouped.items():
        sql = build_ranking_update_sql(fields)
        params = [build_ranking_update_params(fields, u) for u in rows]
        execute_batch(cur, sql, params, page_size=200)


def verify_applied(cur, table, updates, batch_size=500):
    """
    commit 전에 PK(id) 기준으로 계획한 각 업데이트 값이 DB에 반영됐는지 검증.
    누락/불일치가 있으면 RuntimeError → 호출부에서 rollback.
    """
    if not updates:
        return
    assert table in ('works', 'rankings')
    fields_all = sorted({f for u in updates for f in u['set']})
    expected = {u['id']: u['set'] for u in updates}
    ids = list(expected)
    mismatches = []
    for i in range(0, len(ids), batch_size):
        chunk = ids[i:i + batch_size]
        cur.execute(
            f"SELECT id, {', '.join(fields_all)} FROM {table} WHERE id = ANY(%s)",
            (chunk,),
        )
        rows = {row[0]: dict(zip(fields_all, row[1:])) for row in cur.fetchall()}
        for pk in chunk:
            row = rows.get(pk)
            if row is None:
                mismatches.append((pk, '<row>', None, 'missing'))
                continue
            for f, want in expected[pk].items():
                got = clean(row.get(f))
                if got != want:
                    mismatches.append((pk, f, got, want))
    if mismatches:
        sample = ', '.join(
            f'{table}.id={pk} {f}: got={got!r} want={want!r}'
            for pk, f, got, want in mismatches[:5]
        )
        raise RuntimeError(
            f'검증 실패: {table} {len(mismatches)}건 미반영/불일치 → rollback. 예: {sample}'
        )


def main():
    parser = argparse.ArgumentParser(description='works/rankings 메타데이터 백필 (기본 dry-run)')
    parser.add_argument('--apply', action='store_true', help='실제 DB 적용 (미지정 시 dry-run)')
    parser.add_argument('--dry-run', action='store_true', help='명시적 dry-run (기본값과 동일)')
    parser.add_argument('--rankings-scope', choices=['latest', 'all'], default='latest',
                        help='rankings 백필 범위 (기본: latest = 최신 날짜만)')
    args = parser.parse_args()

    if args.apply and args.dry_run:
        print('ERROR: --apply 와 --dry-run 을 동시에 지정할 수 없습니다.')
        sys.exit(1)
    apply_mode = args.apply
    mode_label = 'APPLY' if apply_mode else 'DRY-RUN'

    conn = get_connection()
    try:
        cur = conn.cursor()

        if args.rankings_scope == 'latest':
            cur.execute('SELECT MAX(date) FROM rankings')
            latest = cur.fetchone()[0]
            rankings_where, rankings_params = 'date = %s', (latest,)
            print(f'[{mode_label}] rankings 범위: latest ({latest})')
        else:
            rankings_where, rankings_params = 'TRUE', ()
            print(f'[{mode_label}] rankings 범위: all')

        before = fetch_missing_counts(cur, rankings_where, rankings_params)
        print('\n== 백필 전 누락 집계 ==')
        for k, v in before.items():
            print(f'  {k:22s} 누락 {v}')

        # --- 데이터 로드 ---
        cur.execute('SELECT id, title_kr, publisher, genre, genre_kr FROM unified_works')
        unified_map = {
            row[0]: {'title_kr': row[1], 'publisher': row[2],
                     'genre': row[3], 'genre_kr': row[4]}
            for row in cur.fetchall()
        }
        cur.execute(
            'SELECT id, platform, title, unified_work_id, title_kr, '
            'publisher, genre, genre_kr FROM works'
        )
        works = [
            {'id': r[0], 'platform': r[1], 'title': r[2], 'unified_work_id': r[3],
             'title_kr': r[4], 'publisher': r[5], 'genre': r[6], 'genre_kr': r[7]}
            for r in cur.fetchall()
        ]

        work_updates, work_stats = plan_work_updates(works, unified_map)

        links = work_stats['links']
        print('\n== 링크 검증 (works.title_kr == unified_works.title_kr) ==')
        print(f"  verified {links['verified']} | mismatch {links['mismatch']} (전파 제외) | "
              f"unverifiable {links['unverifiable']} (전파 제외) | unlinked {links['unlinked']}")

        print('\n== works 백필 계획 (verified 연결만) ==')
        for f in WORK_FIELDS:
            print(f'  {f:10s} 채움 {work_stats["filled"][f]:6d} | '
                  f'충돌 미적용 {work_stats["conflicts"][f]}')
        print(f'  장르쌍 소스 불일치로 미적용: {work_stats["pair_mix_skipped"]}')

        # --- rankings ---
        cur.execute(
            'SELECT id, date, platform, sub_category, rank, title, genre, genre_kr '
            f'FROM rankings WHERE (genre IS NULL OR TRIM(genre) = %s '
            f"OR genre_kr IS NULL OR TRIM(genre_kr) = %s) AND {rankings_where}",
            ('', '') + rankings_params,
        )
        ranking_rows = [
            {'id': r[0], 'date': r[1], 'platform': r[2], 'sub_category': r[3],
             'rank': r[4], 'title': r[5], 'genre': r[6], 'genre_kr': r[7]}
            for r in cur.fetchall()
        ]
        # works 백필 계획을 반영한 유효값으로 rankings 를 채운다
        planned = {(u['platform'], u['title']): u['set'] for u in work_updates}
        works_effective = []
        for w in works:
            merged = dict(w)
            for f, v in planned.get((w['platform'], w['title']), {}).items():
                if clean(merged.get(f)) is None:
                    merged[f] = v
            works_effective.append(merged)
        works_meta = effective_work_meta(works_effective, unified_map)
        ranking_updates, ranking_stats = plan_ranking_updates(ranking_rows, works_meta)

        print('\n== rankings 백필 계획 ==')
        for f in RANKING_FIELDS:
            print(f'  {f:10s} 채움 {ranking_stats["filled"][f]}')
        print(f'  소스 없음(works/unified 미연결·미보유): {ranking_stats["no_source"]}')
        print(f'  기존 값과 소스 충돌로 미적용: {ranking_stats["pair_conflicts"]}')

        if apply_mode:
            apply_work_updates(cur, work_updates)
            apply_ranking_updates(cur, ranking_updates)
            # commit 전 PK 기준 반영 검증 — 실패 시 예외 → rollback
            verify_applied(cur, 'works', work_updates)
            verify_applied(cur, 'rankings', ranking_updates)
            # 적용 후 누락 집계도 commit 전에 실행 — 실패 시 예외 → rollback
            after = fetch_missing_counts(cur, rankings_where, rankings_params)
            # 모든 검증·집계 성공 후에만 commit. 이후에는 저장된 after 출력만.
            conn.commit()
            print('\n== 적용 후 누락 집계 ==')
            for k, v in after.items():
                print(f'  {k:22s} 누락 {v} (이전 {before[k]})')
            print('\n적용 완료 (검증 통과 후 커밋됨).')
        else:
            conn.rollback()
            print('\n== dry-run 예상 결과 (적용 시) ==')
            for f in WORK_FIELDS:
                key = f'works.{f}'
                print(f'  {key:22s} 누락 {before[key]} → {before[key] - work_stats["filled"][f]}')
            for f in RANKING_FIELDS:
                key = f'rankings.{f}'
                print(f'  {key:22s} 누락 {before[key]} → {before[key] - ranking_stats["filled"][f]}')
            print('\nDRY-RUN: DB 는 변경되지 않았습니다. 적용하려면 --apply 를 지정하세요.')
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    main()
