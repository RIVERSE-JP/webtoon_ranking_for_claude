import { sql } from "@/lib/supabase";
import type { Ranking, PlatformStats } from "@/lib/types";
import { DashboardClient } from "@/components/dashboard-client";
import { PLATFORMS } from "@/lib/constants";
import { generateTrendReport } from "@/lib/trend-report";

// ISR: 5분마다 백그라운드 재생성 → Vercel CDN이 캐시 → 첫 방문자도 즉시 응답
export const revalidate = 300;
// 데이터 양 증가 대응: SSR function timeout을 60초로 (Vercel 기본 10초)
export const maxDuration = 60;

type InitialData = {
  dates: string[];
  latestDate: string;
  lastUpdated: Record<string, string>;
  stats: Record<string, PlatformStats>;
  riverseCounts: Record<string, number>;
  rankings: Ranking[];
  defaultPlatform: string;
};

async function getInitialData(): Promise<InitialData | null> {
  try {
    const defaultPlatform = "piccoma";

    const dateRows = await sql`
      SELECT date::text as date, MAX(created_at) as last_updated
      FROM rankings GROUP BY date ORDER BY date DESC
    `;
    const dates: string[] = dateRows.map((r) => String(r.date));
    const lastUpdated: Record<string, string> = {};
    for (const r of dateRows) {
      lastUpdated[r.date] = r.last_updated;
    }
    const latestDate = dates[0] || "";

    if (!latestDate) {
      return { dates, latestDate, lastUpdated, stats: {}, riverseCounts: {}, rankings: [], defaultPlatform };
    }

    const overallKeys = [...new Set(PLATFORMS.map((p) => p.genres[0]?.key ?? ""))];

    const [statsRows, riverseCountRows, rankingRows, prevDateRows] = await Promise.all([
      sql`
        SELECT platform, COUNT(*)::int as total,
               COUNT(*) FILTER (WHERE is_riverse = TRUE)::int as riverse
        FROM rankings
        WHERE date = ${latestDate} AND COALESCE(sub_category, '') = ANY(${overallKeys})
        GROUP BY platform
      `,
      sql`
        SELECT COALESCE(sub_category, '') as sub_category, COUNT(*)::int as count
        FROM rankings
        WHERE date = ${latestDate} AND platform = ${defaultPlatform} AND is_riverse = TRUE
        GROUP BY COALESCE(sub_category, '')
      `,
      sql`
        SELECT rank::int as rank, title, title_kr, genre, genre_kr, url, is_riverse
        FROM rankings
        WHERE date = ${latestDate} AND platform = ${defaultPlatform} AND COALESCE(sub_category, '') = ''
        ORDER BY rank
      `,
      sql`
        SELECT DISTINCT date::text as date FROM rankings
        WHERE date < ${latestDate} AND platform = ${defaultPlatform}
        ORDER BY date DESC LIMIT 1
      `,
    ]);

    const stats: Record<string, PlatformStats> = {};
    for (const r of statsRows) {
      stats[r.platform] = { total: r.total, riverse: r.riverse };
    }

    const riverseCounts: Record<string, number> = {};
    for (const r of riverseCountRows) {
      riverseCounts[r.sub_category] = r.count;
    }

    const titles = rankingRows.map((r) => r.title);
    const [prevRankings, thumbRows] = await Promise.all([
      prevDateRows.length > 0
        ? sql`
            SELECT title, rank::int as rank FROM rankings
            WHERE date = ${prevDateRows[0].date} AND platform = ${defaultPlatform}
              AND COALESCE(sub_category, '') = ''
              AND title = ANY(${titles})
          `
        : Promise.resolve([]),
      titles.length > 0
        ? sql`
            SELECT title, thumbnail_url, unified_work_id, publisher
            FROM works
            WHERE platform = ${defaultPlatform}
              AND title = ANY(${titles})
          `
        : Promise.resolve([]),
    ]);

    const rankChanges: Record<string, number> = {};
    if (prevRankings.length > 0) {
      const prevMap: Record<string, number> = {};
      for (const r of prevRankings) prevMap[r.title] = r.rank;

      const newTitles = rankingRows
        .filter((r) => !(r.title in prevMap))
        .map((r) => r.title);

      let everSeenSet = new Set<string>();
      if (newTitles.length > 0) {
        const everSeenRows = await sql`
          SELECT DISTINCT title FROM rankings
          WHERE platform = ${defaultPlatform} AND title = ANY(${newTitles})
            AND date < ${latestDate}
        `;
        everSeenSet = new Set(everSeenRows.map((r) => r.title));
      }

      for (const r of rankingRows) {
        if (r.title in prevMap) {
          rankChanges[r.title] = prevMap[r.title] - r.rank;
        } else if (everSeenSet.has(r.title)) {
          rankChanges[r.title] = 998; // 재진입
        } else {
          rankChanges[r.title] = 999; // NEW
        }
      }
    }

    const thumbnails: Record<string, string> = {};
    const unifiedIds: Record<string, number> = {};
    const publishers: Record<string, string> = {};
    for (const t of thumbRows) {
      if (t.thumbnail_url) thumbnails[t.title] = t.thumbnail_url;
      if (t.unified_work_id) unifiedIds[t.title] = t.unified_work_id;
      if (t.publisher) publishers[t.title] = t.publisher;
    }

    const rankings: Ranking[] = rankingRows.map((r) => ({
      rank: r.rank,
      title: r.title,
      title_kr: r.title_kr || null,
      genre: r.genre || null,
      genre_kr: r.genre_kr || null,
      url: r.url,
      is_riverse: r.is_riverse,
      rank_change: rankChanges[r.title] ?? 0,
      thumbnail_url: thumbnails[r.title] || undefined,
      unified_work_id: unifiedIds[r.title] || null,
      publisher: publishers[r.title] || null,
    }));

    return { dates, latestDate, lastUpdated, stats, riverseCounts, rankings, defaultPlatform };
  } catch (e) {
    // 빌드 시 DB 연결 불가 → null 반환 → 빌드 통과 → 런타임에 ISR 재생성
    console.error("[getInitialData] failed:", e);
    return null;
  }
}

export default async function Home() {
  // trend-report가 timeout/throw해도 dashboard 본체는 살리도록 분리
  const [dataR, trendR] = await Promise.allSettled([
    getInitialData(),
    generateTrendReport(),
  ]);
  const data = dataR.status === "fulfilled" ? dataR.value : null;
  const trendReport = trendR.status === "fulfilled" ? trendR.value : null;

  if (!data || !data.latestDate) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <p className="text-muted-foreground">데이터를 불러오는 중...</p>
      </div>
    );
  }

  return (
    <DashboardClient
      initialDates={data.dates}
      initialDate={data.latestDate}
      initialLastUpdated={data.lastUpdated}
      initialStats={data.stats}
      initialRiverseCounts={data.riverseCounts}
      initialRankings={data.rankings}
      initialPlatform={data.defaultPlatform}
      trendReport={trendReport}
    />
  );
}
