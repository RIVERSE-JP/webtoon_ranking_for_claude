import { NextRequest, NextResponse } from "next/server";
import { sql } from "@/lib/supabase";

/**
 * 리버스 작품의 기간별 랭크인 분석
 *
 * Query params:
 *   - start: YYYY-MM-DD (필수)
 *   - end:   YYYY-MM-DD (필수)
 *   - mode:  "platform" | "unified"  (기본 platform)
 *            platform: 플랫폼별로 같은 작품도 분리
 *            unified:  unified_work_id 기준 통합 (크로스플랫폼)
 *   - scope: "main" | "all"  (기본 main)
 *            main: sub_category='' 총합 카테고리만
 *            all:  모든 카테고리 합산
 */
export async function GET(request: NextRequest) {
  const { searchParams } = request.nextUrl;
  const start = searchParams.get("start") || "";
  const end = searchParams.get("end") || "";
  const mode = (searchParams.get("mode") || "platform") as "platform" | "unified";
  const scope = (searchParams.get("scope") || "main") as "main" | "all";

  if (!start || !end) {
    return NextResponse.json({ error: "start and end required" }, { status: 400 });
  }

  const subCategoryFilter =
    scope === "main" ? sql`AND COALESCE(r.sub_category, '') = ''` : sql``;

  // 기간 내 일수 계산용
  const dateRangeRows = await sql`
    SELECT COUNT(DISTINCT date)::int AS total_days
    FROM rankings
    WHERE date BETWEEN ${start} AND ${end}
  `;
  const totalDays = dateRangeRows[0]?.total_days ?? 0;

  let rows: Record<string, unknown>[];

  if (mode === "platform") {
    // 플랫폼별 작품 분석
    rows = await sql`
      SELECT
        r.title,
        MAX(r.title_kr) AS title_kr,
        r.platform,
        w.unified_work_id,
        COUNT(*) FILTER (WHERE r.rank = 1)::int  AS rank1_count,
        COUNT(*) FILTER (WHERE r.rank = 2)::int  AS rank2_count,
        COUNT(*) FILTER (WHERE r.rank = 3)::int  AS rank3_count,
        COUNT(*) FILTER (WHERE r.rank <= 3)::int  AS top3_count,
        COUNT(*) FILTER (WHERE r.rank <= 10)::int AS top10_count,
        COUNT(*)::int AS total_appearances,
        COUNT(DISTINCT r.date)::int AS days_ranked,
        MIN(r.rank)::int AS best_rank,
        ROUND(AVG(r.rank)::numeric, 1)::float AS avg_rank
      FROM rankings r
      LEFT JOIN works w ON r.title = w.title AND r.platform = w.platform
      WHERE r.is_riverse = TRUE
        AND r.date BETWEEN ${start} AND ${end}
        ${subCategoryFilter}
      GROUP BY r.title, r.platform, w.unified_work_id
      ORDER BY top3_count DESC, rank1_count DESC, total_appearances DESC
      LIMIT 200
    `;
  } else {
    // unified_work_id 기준 통합
    rows = await sql`
      SELECT
        COALESCE(MAX(uw.title_kr), MAX(r.title_kr), MAX(r.title)) AS title,
        MAX(uw.title_kr) AS title_kr,
        STRING_AGG(DISTINCT r.platform, ',') AS platforms,
        COUNT(DISTINCT r.platform)::int AS platform_count,
        w.unified_work_id,
        COUNT(*) FILTER (WHERE r.rank = 1)::int  AS rank1_count,
        COUNT(*) FILTER (WHERE r.rank = 2)::int  AS rank2_count,
        COUNT(*) FILTER (WHERE r.rank = 3)::int  AS rank3_count,
        COUNT(*) FILTER (WHERE r.rank <= 3)::int  AS top3_count,
        COUNT(*) FILTER (WHERE r.rank <= 10)::int AS top10_count,
        COUNT(*)::int AS total_appearances,
        COUNT(DISTINCT r.date)::int AS days_ranked,
        MIN(r.rank)::int AS best_rank,
        ROUND(AVG(r.rank)::numeric, 1)::float AS avg_rank
      FROM rankings r
      LEFT JOIN works w ON r.title = w.title AND r.platform = w.platform
      LEFT JOIN unified_works uw ON w.unified_work_id = uw.id
      WHERE r.is_riverse = TRUE
        AND w.unified_work_id IS NOT NULL
        AND r.date BETWEEN ${start} AND ${end}
        ${subCategoryFilter}
      GROUP BY w.unified_work_id
      ORDER BY top3_count DESC, rank1_count DESC, total_appearances DESC
      LIMIT 200
    `;
  }

  // 요약 KPI 계산
  const summary = {
    total_days: totalDays,
    unique_works: rows.length,
    works_with_rank1: rows.filter((r) => Number(r.rank1_count) > 0).length,
    works_with_top3: rows.filter((r) => Number(r.top3_count) > 0).length,
    works_with_top10: rows.filter((r) => Number(r.top10_count) > 0).length,
    total_appearances: rows.reduce((s, r) => s + Number(r.total_appearances), 0),
  };

  return NextResponse.json(
    { summary, works: rows, mode, scope, start, end },
    {
      headers: {
        "Cache-Control": "public, s-maxage=300, stale-while-revalidate=600",
      },
    }
  );
}
