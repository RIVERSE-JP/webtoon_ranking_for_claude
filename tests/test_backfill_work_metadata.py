import importlib.util
import unittest
from pathlib import Path

# scripts/ 는 패키지가 아니므로 파일 경로로 직접 로드한다.
# 모듈 import 시 DB 의존성(psycopg2/dotenv)이 없어야 한다는 점도 함께 검증된다.
MODULE_PATH = (
    Path(__file__).resolve().parent.parent / 'scripts' / 'backfill_work_metadata.py'
)
spec = importlib.util.spec_from_file_location('backfill_work_metadata', MODULE_PATH)
bf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bf)


class CleanTests(unittest.TestCase):
    def test_none_and_empty_and_whitespace_are_none(self):
        self.assertIsNone(bf.clean(None))
        self.assertIsNone(bf.clean(''))
        self.assertIsNone(bf.clean('   '))

    def test_strips_surrounding_whitespace(self):
        self.assertEqual(bf.clean('  講談社  '), '講談社')


class LinkStatusTests(unittest.TestCase):
    def test_unlinked_when_no_unified_id_or_record(self):
        self.assertEqual(bf.link_status({'unified_work_id': None}, None), 'unlinked')
        self.assertEqual(bf.link_status({'unified_work_id': 1}, None), 'unlinked')

    def test_unverifiable_when_either_title_kr_missing(self):
        w = {'unified_work_id': 1, 'title_kr': ''}
        self.assertEqual(bf.link_status(w, {'title_kr': '나혼렙'}), 'unverifiable')
        w = {'unified_work_id': 1, 'title_kr': '나혼렙'}
        self.assertEqual(bf.link_status(w, {'title_kr': '  '}), 'unverifiable')

    def test_mismatch_when_title_kr_differs(self):
        w = {'unified_work_id': 1, 'title_kr': '나 혼자만 레벨업'}
        self.assertEqual(bf.link_status(w, {'title_kr': '전지적 독자 시점'}), 'mismatch')

    def test_verified_when_title_kr_exact_match_after_trim(self):
        w = {'unified_work_id': 1, 'title_kr': ' 나 혼자만 레벨업 '}
        self.assertEqual(bf.link_status(w, {'title_kr': '나 혼자만 레벨업'}), 'verified')


class ResolveFieldTests(unittest.TestCase):
    def test_non_empty_current_is_never_overwritten(self):
        value, conflict = bf.resolve_field('集英社', ['講談社', '小学館'])
        self.assertIsNone(value)
        self.assertFalse(conflict)

    def test_whitespace_only_current_is_treated_as_missing(self):
        value, conflict = bf.resolve_field('  ', ['講談社'])
        self.assertEqual(value, '講談社')
        self.assertFalse(conflict)

    def test_no_candidates_returns_nothing(self):
        value, conflict = bf.resolve_field(None, ['', '  ', None])
        self.assertIsNone(value)
        self.assertFalse(conflict)

    def test_single_distinct_candidate_is_filled(self):
        value, conflict = bf.resolve_field(None, ['판타지', ' 판타지 '])
        self.assertEqual(value, '판타지')
        self.assertFalse(conflict)

    def test_any_conflict_is_not_applied(self):
        # publisher/genre/genre_kr 모두 동일한 보수 정책: 충돌 시 미적용
        value, conflict = bf.resolve_field(None, ['講談社', '集英社'])
        self.assertIsNone(value)
        self.assertTrue(conflict)


class GenreFillCompatibleTests(unittest.TestCase):
    def test_pair_present_in_single_source(self):
        row = {'genre': '', 'genre_kr': ''}
        sources = [{'genre': 'ファンタジー', 'genre_kr': '판타지'}]
        self.assertTrue(bf.genre_fill_compatible(
            {'genre': 'ファンタジー', 'genre_kr': '판타지'}, row, sources))

    def test_pair_split_across_sources_is_rejected(self):
        row = {'genre': '', 'genre_kr': ''}
        sources = [
            {'genre': 'ファンタジー', 'genre_kr': None},
            {'genre': None, 'genre_kr': '판타지'},
        ]
        self.assertFalse(bf.genre_fill_compatible(
            {'genre': 'ファンタジー', 'genre_kr': '판타지'}, row, sources))

    def test_single_fill_conflicting_with_existing_value_is_rejected(self):
        # 기존 genre 와 다른 genre 를 가진 소스에서 genre_kr 만 가져오면 섞임
        row = {'genre': 'ラブコメ', 'genre_kr': ''}
        sources = [{'genre': 'ファンタジー', 'genre_kr': '판타지'}]
        self.assertFalse(
            bf.genre_fill_compatible({'genre_kr': '판타지'}, row, sources))

    def test_single_fill_from_source_without_other_field_is_allowed(self):
        row = {'genre': 'ラブコメ', 'genre_kr': ''}
        sources = [{'genre': None, 'genre_kr': '러브코미디'}]
        self.assertTrue(
            bf.genre_fill_compatible({'genre_kr': '러브코미디'}, row, sources))


class PlanWorkUpdatesTests(unittest.TestCase):
    def _works(self):
        return [
            {'id': 10, 'platform': 'piccoma', 'title': 'A', 'unified_work_id': 1,
             'title_kr': '작품A', 'publisher': '', 'genre': None, 'genre_kr': ''},
            {'id': 11, 'platform': 'cmoa', 'title': 'A-cmoa', 'unified_work_id': 1,
             'title_kr': '작품A', 'publisher': '集英社',
             'genre': 'ファンタジー', 'genre_kr': '판타지'},
            {'id': 12, 'platform': 'renta', 'title': 'B', 'unified_work_id': None,
             'title_kr': '', 'publisher': '', 'genre': '', 'genre_kr': ''},
        ]

    def _unified(self, **over):
        base = {'title_kr': '작품A', 'publisher': None, 'genre': None, 'genre_kr': None}
        base.update(over)
        return {1: base}

    def test_fills_from_unified_and_verified_siblings(self):
        updates, stats = bf.plan_work_updates(self._works(), self._unified())
        self.assertEqual(len(updates), 1)
        u = updates[0]
        self.assertEqual(u['id'], 10)
        self.assertEqual(u['unified_work_id'], 1)
        self.assertEqual(u['title_kr'], '작품A')  # UPDATE WHERE 재검증용 계획값
        # 형제(cmoa)가 verified 이고 단일값 → 채움. 장르쌍도 동일 소스(cmoa)에 존재.
        self.assertEqual(u['set'], {
            'publisher': '集英社', 'genre': 'ファンタジー', 'genre_kr': '판타지',
        })
        self.assertEqual(stats['filled'], {'publisher': 1, 'genre': 1, 'genre_kr': 1})
        self.assertEqual(sum(stats['conflicts'].values()), 0)
        self.assertEqual(stats['links'],
                         {'verified': 2, 'mismatch': 0, 'unverifiable': 0, 'unlinked': 1})

    def test_mismatch_link_is_excluded_from_propagation(self):
        works = self._works()
        works[0]['title_kr'] = '전혀 다른 제목'  # unified 와 불일치
        updates, stats = bf.plan_work_updates(works, self._unified())
        self.assertEqual(updates, [])
        self.assertEqual(stats['links']['mismatch'], 1)

    def test_unverifiable_link_is_excluded_from_propagation(self):
        works = self._works()
        works[0]['title_kr'] = ''  # 검증 불가
        updates, stats = bf.plan_work_updates(works, self._unified())
        self.assertEqual(updates, [])
        self.assertEqual(stats['links']['unverifiable'], 1)

    def test_unverified_sibling_is_not_a_candidate(self):
        works = self._works()
        works[1]['title_kr'] = '다른제목'  # 형제가 mismatch → 후보 제외
        updates, stats = bf.plan_work_updates(works, self._unified())
        # unified 에는 값이 없으므로 채울 것이 없다
        self.assertEqual(updates, [])
        self.assertEqual(stats['filled'], {'publisher': 0, 'genre': 0, 'genre_kr': 0})

    def test_publisher_conflict_skipped_and_counted(self):
        updates, stats = bf.plan_work_updates(
            self._works(), self._unified(publisher='講談社'))
        u = updates[0]
        self.assertNotIn('publisher', u['set'])
        self.assertEqual(stats['conflicts']['publisher'], 1)
        self.assertEqual(stats['filled']['publisher'], 0)

    def test_genre_conflict_is_also_skipped(self):
        # genre 도 publisher 와 동일한 보수 정책
        updates, stats = bf.plan_work_updates(
            self._works(), self._unified(genre='ラブコメ'))
        u = updates[0]
        self.assertNotIn('genre', u['set'])
        self.assertEqual(stats['conflicts']['genre'], 1)

    def test_genre_pair_from_split_sources_is_skipped(self):
        works = [
            {'id': 10, 'platform': 'piccoma', 'title': 'A', 'unified_work_id': 1,
             'title_kr': '작품A', 'publisher': '', 'genre': '', 'genre_kr': ''},
            {'id': 11, 'platform': 'cmoa', 'title': 'A2', 'unified_work_id': 1,
             'title_kr': '작품A', 'publisher': '', 'genre': 'ファンタジー', 'genre_kr': ''},
        ]
        unified = {1: {'title_kr': '작품A', 'publisher': None,
                       'genre': None, 'genre_kr': '판타지'}}
        updates, stats = bf.plan_work_updates(works, unified)
        # id 10: genre 는 형제, genre_kr 는 unified → 소스가 갈려서 둘 다 미적용
        self.assertEqual(stats['pair_mix_skipped'], 1)
        self.assertTrue(all(u['id'] != 10 for u in updates))
        # id 11: unified 가 genre 를 비워 두었으므로 genre_kr 단독 채움은 허용
        u11 = next(u for u in updates if u['id'] == 11)
        self.assertEqual(u11['set'], {'genre_kr': '판타지'})

    def test_non_empty_values_untouched(self):
        works = [
            {'id': 10, 'platform': 'piccoma', 'title': 'A', 'unified_work_id': 1,
             'title_kr': '작품A', 'publisher': '既存', 'genre': '既存', 'genre_kr': '기존'},
        ]
        unified = {1: {'title_kr': '작품A', 'publisher': '다른값',
                       'genre': '다른값', 'genre_kr': '다른값'}}
        updates, _ = bf.plan_work_updates(works, unified)
        self.assertEqual(updates, [])


class EffectiveWorkMetaTests(unittest.TestCase):
    def test_works_pair_wins_and_is_not_mixed_with_unified(self):
        works = [{'id': 1, 'platform': 'piccoma', 'title': 'A', 'unified_work_id': 1,
                  'title_kr': '작품A', 'genre': '直接', 'genre_kr': ''}]
        unified_map = {1: {'title_kr': '작품A',
                           'genre': 'unified장르', 'genre_kr': 'unified장르kr'}}
        meta = bf.effective_work_meta(works, unified_map)
        # works 에 genre 가 있으므로 works 쌍만 사용 — unified 의 genre_kr 를 섞지 않음
        self.assertEqual(meta[('piccoma', 'A')], {'genre': '直接'})

    def test_unified_pair_used_only_when_verified(self):
        works = [{'id': 1, 'platform': 'piccoma', 'title': 'A', 'unified_work_id': 1,
                  'title_kr': '다른제목', 'genre': '', 'genre_kr': ''}]
        unified_map = {1: {'title_kr': '작품A', 'genre': 'G', 'genre_kr': 'GK'}}
        self.assertEqual(bf.effective_work_meta(works, unified_map), {})
        works[0]['title_kr'] = '작품A'
        self.assertEqual(bf.effective_work_meta(works, unified_map),
                         {('piccoma', 'A'): {'genre': 'G', 'genre_kr': 'GK'}})

    def test_work_without_any_value_is_excluded(self):
        works = [{'id': 1, 'platform': 'piccoma', 'title': 'A', 'unified_work_id': None,
                  'title_kr': '', 'genre': '', 'genre_kr': None}]
        self.assertEqual(bf.effective_work_meta(works, {}), {})


class PlanRankingUpdatesTests(unittest.TestCase):
    def test_fills_only_missing_fields_with_exact_match(self):
        rankings = [
            {'id': 100, 'date': '2026-09-02', 'platform': 'piccoma',
             'sub_category': None, 'rank': 1, 'title': 'A',
             'genre': '', 'genre_kr': None},
            {'id': 101, 'date': '2026-09-02', 'platform': 'piccoma',
             'sub_category': 'smartoon', 'rank': 2, 'title': 'B',
             'genre': '있음', 'genre_kr': '있음'},
            {'id': 102, 'date': '2026-09-02', 'platform': 'piccoma',
             'sub_category': None, 'rank': 3, 'title': 'C',
             'genre': '', 'genre_kr': ''},
        ]
        works_meta = {('piccoma', 'A'): {'genre': 'ファンタジー', 'genre_kr': '판타지'}}
        updates, stats = bf.plan_ranking_updates(rankings, works_meta)
        self.assertEqual(len(updates), 1)
        u = updates[0]
        self.assertEqual(u['id'], 100)
        self.assertEqual(u['set'], {'genre': 'ファンタジー', 'genre_kr': '판타지'})
        self.assertEqual(stats['filled'], {'genre': 1, 'genre_kr': 1})
        self.assertEqual(stats['no_source'], 1)  # C: 소스 없음

    def test_existing_field_conflicting_with_source_blocks_fill(self):
        # 기존 genre 가 소스의 genre 와 다르면 genre_kr 를 그 소스에서 채우지 않는다
        rankings = [
            {'id': 100, 'date': '2026-09-02', 'platform': 'cmoa', 'sub_category': '',
             'rank': 1, 'title': 'A', 'genre': 'ラブコメ', 'genre_kr': ''},
        ]
        works_meta = {('cmoa', 'A'): {'genre': '다른장르', 'genre_kr': '러브코미디'}}
        updates, stats = bf.plan_ranking_updates(rankings, works_meta)
        self.assertEqual(updates, [])
        self.assertEqual(stats['pair_conflicts'], 1)

    def test_existing_field_matching_source_allows_fill(self):
        rankings = [
            {'id': 100, 'date': '2026-09-02', 'platform': 'cmoa', 'sub_category': '',
             'rank': 1, 'title': 'A', 'genre': 'ラブコメ', 'genre_kr': ''},
        ]
        works_meta = {('cmoa', 'A'): {'genre': 'ラブコメ', 'genre_kr': '러브코미디'}}
        updates, stats = bf.plan_ranking_updates(rankings, works_meta)
        self.assertEqual(updates[0]['set'], {'genre_kr': '러브코미디'})
        self.assertEqual(stats['filled'], {'genre': 0, 'genre_kr': 1})


class SqlShapeTests(unittest.TestCase):
    """UPDATE SQL 이 PK 기반 + 계획값 재검증 + 기존값 보호 형태인지 검증."""

    def test_work_update_sql_reverifies_unified_id_and_title_kr(self):
        sql = bf.build_work_update_sql(('genre', 'publisher'))
        # 동시변경 차단: id + unified_work_id + 계획 당시 title_kr(trim exact)
        self.assertIn(
            'WHERE id = %s AND unified_work_id = %s AND TRIM(title_kr) = %s', sql)
        for f in ('genre', 'publisher'):
            self.assertIn(
                f"{f} = CASE WHEN {f} IS NULL OR TRIM({f}) = '' THEN %s ELSE {f} END",
                sql,
            )
        # 기존 비어 있지 않은 값을 TRIM 으로 재작성하는 패턴이 없어야 한다
        self.assertNotIn('COALESCE(NULLIF(TRIM', sql)

    def test_ranking_update_sql_reverifies_platform_title_and_still_empty(self):
        sql = bf.build_ranking_update_sql(('genre', 'genre_kr'))
        # 동시변경 차단: id + 계획 당시 platform / title 정확 재검증
        self.assertIn('WHERE id = %s AND platform = %s AND title = %s AND (', sql)
        self.assertIn("(genre IS NULL OR TRIM(genre) = '')", sql)
        self.assertIn("(genre_kr IS NULL OR TRIM(genre_kr) = '')", sql)
        self.assertIn("CASE WHEN genre IS NULL OR TRIM(genre) = ''", sql)
        self.assertNotIn('COALESCE(NULLIF(TRIM', sql)
        self.assertNotIn('date = %s', sql)


class UpdateParamsTests(unittest.TestCase):
    """파라미터 순서가 SQL placeholder 순서(SET → WHERE)와 일치하는지 검증."""

    def test_work_params_include_id_unified_id_and_title_kr(self):
        fields = ('genre', 'publisher')
        u = {'id': 10, 'platform': 'piccoma', 'title': 'A', 'unified_work_id': 1,
             'title_kr': '작품A', 'set': {'publisher': '集英社', 'genre': 'ファンタジー'}}
        self.assertEqual(
            bf.build_work_update_params(fields, u),
            ('ファンタジー', '集英社', 10, 1, '작품A'),
        )

    def test_ranking_params_include_id_platform_and_title(self):
        fields = ('genre', 'genre_kr')
        u = {'id': 100, 'platform': 'piccoma', 'title': 'A',
             'set': {'genre': 'ファンタジー', 'genre_kr': '판타지'}}
        self.assertEqual(
            bf.build_ranking_update_params(fields, u),
            ('ファンタジー', '판타지', 100, 'piccoma', 'A'),
        )

    def test_work_params_match_sql_placeholder_count(self):
        fields = ('publisher',)
        sql = bf.build_work_update_sql(fields)
        u = {'id': 10, 'unified_work_id': 1, 'title_kr': '작품A',
             'set': {'publisher': '集英社'}}
        self.assertEqual(sql.count('%s'), len(bf.build_work_update_params(fields, u)))

    def test_ranking_params_match_sql_placeholder_count(self):
        fields = ('genre_kr',)
        sql = bf.build_ranking_update_sql(fields)
        u = {'id': 100, 'platform': 'cmoa', 'title': 'B', 'set': {'genre_kr': '판타지'}}
        self.assertEqual(sql.count('%s'), len(bf.build_ranking_update_params(fields, u)))


if __name__ == '__main__':
    unittest.main()
