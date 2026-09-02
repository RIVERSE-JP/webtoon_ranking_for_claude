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
            SELECT w.title, w.thumbnail_url, w.thumbnail_base64, w.unified_work_id,
                   COALESCE(NULLIF(TRIM(w.publisher), ''), NULLIF(TRIM(u.publisher), '')) AS publisher,
                   NULLIF(TRIM(w.genre), '') AS w_genre,
                   NULLIF(TRIM(w.genre_kr), '') AS w_genre_kr,
                   NULLIF(TRIM(u.genre), '') AS u_genre,
                   NULLIF(TRIM(u.genre_kr), '') AS u_genre_kr
            FROM works w
            LEFT JOIN unified_works u
              ON u.id = w.unified_work_id
             AND NULLIF(TRIM(w.title_kr), '') = NULLIF(TRIM(u.title_kr), '')
            WHERE w.platform = ${defaultPlatform}
              AND w.title = ANY(${titles})
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
    const genres: Record<string, string> = {};
    const genreKrs: Record<string, string> = {};
    for (const t of thumbRows) {
      if (t.thumbnail_url || t.thumbnail_base64) thumbnails[String(t.title)] = String(t.thumbnail_url || t.thumbnail_base64);
      if (t.unified_work_id) unifiedIds[t.title] = t.unified_work_id;
      if (t.publisher) publishers[t.title] = t.publisher;
      // 장르쌍은 works 한 소스만 사용하고, works에 둘 다 없을 때만
      // title_kr가 검증된 unified 쌍을 사용한다.
      const useWorksPair = Boolean(t.w_genre || t.w_genre_kr);
      const genre = useWorksPair ? t.w_genre : t.u_genre;
      const genreKr = useWorksPair ? t.w_genre_kr : t.u_genre_kr;
      if (genre) genres[t.title] = genre;
      if (genreKr) genreKrs[t.title] = genreKr;
    }

    const rankings: Ranking[] = rankingRows.map((r) => {
      // rankings에 장르쌍 중 하나라도 있으면 rankings 값만 사용한다.
      // 둘 다 없을 때만 works/unified의 단일 소스 쌍으로 fallback한다.
      const rGenre = (r.genre && String(r.genre).trim()) || null;
      const rGenreKr = (r.genre_kr && String(r.genre_kr).trim()) || null;
      const useRankingPair = Boolean(rGenre || rGenreKr);
      return {
        rank: r.rank,
        title: r.title,
        title_kr: r.title_kr || null,
        genre: useRankingPair ? rGenre : genres[r.title] || null,
        genre_kr: useRankingPair ? rGenreKr : genreKrs[r.title] || null,
        url: r.url,
        is_riverse: r.is_riverse,
        rank_change: rankChanges[r.title] ?? 0,
        thumbnail_url: thumbnails[r.title] || undefined,
        unified_work_id: unifiedIds[r.title] || null,
        publisher: publishers[r.title] || null,
      };
    });

    return { dates, latestDate, lastUpdated, stats, riverseCounts, rankings, defaultPlatform };
  } catch (e) {
    // 빌드 시 DB 연결 불가 → null 반환 → 빌드 통과 → 런타임에 ISR 재생성
    console.error("[getInitialData] failed:", e);
    return null;
  }
}

export default async function Home() {
  // 1단계: dashboard 본체 데이터만 먼저 가져옴 (절대 trend-report와 묶지 않음)
  const data = await getInitialData();

  if (!data || !data.latestDate) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <p className="text-muted-foreground">
          데이터를 불러오는 중...
          <br />
          <span className="text-xs opacity-50">
            (data={String(!!data)} latestDate={data?.latestDate || "(empty)"})
          </span>
        </p>
      </div>
    );
  }

  // 2단계: trend-report는 별도 try/catch. 실패해도 dashboard는 표시.
  let trendReport: Awaited<ReturnType<typeof generateTrendReport>> = null;
  try {
    trendReport = await generateTrendReport();
  } catch (e) {
    console.error("[page] trend-report failed:", e);
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
