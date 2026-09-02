import { NextRequest, NextResponse } from "next/server";
import { sql } from "@/lib/supabase";

export async function GET(request: NextRequest) {
  const { searchParams } = request.nextUrl;
  const date = searchParams.get("date") || "";
  const platform = searchParams.get("platform") || "";
  const subCategory = searchParams.get("sub_category") || "";

  if (!date || !platform) {
    return NextResponse.json({ error: "date and platform required" }, { status: 400 });
  }

  // 모든 쿼리를 병렬로 실행
  const [rankings, prevDateRows] = await Promise.all([
    // 현재 랭킹
    sql`
      SELECT rank, title, title_kr, genre, genre_kr, url, is_riverse
      FROM rankings
      WHERE date = ${date} AND platform = ${platform} AND COALESCE(sub_category, '') = ${subCategory}
      ORDER BY rank
    `,
    // 이전 날짜 찾기
    sql`
      SELECT DISTINCT date FROM rankings
      WHERE date < ${date} AND platform = ${platform}
      ORDER BY date DESC LIMIT 1
    `,
  ]);

  // 랭킹 타이틀 목록으로 썸네일만 필터링 (전체 works 로드 대신)
  const titles = rankings.map((r) => r.title);

  // 이전 랭킹 & 썸네일을 병렬로 (타이틀 기반 필터)
  const [prevRankings, thumbRows] = await Promise.all([
    prevDateRows.length > 0
      ? sql`
          SELECT title, rank FROM rankings
          WHERE date = ${prevDateRows[0].date} AND platform = ${platform}
            AND COALESCE(sub_category, '') = ${subCategory}
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
          WHERE w.platform = ${platform}
            AND w.title = ANY(${titles})
        `
      : Promise.resolve([]),
  ]);

  // rank changes 계산
  const rankChanges: Record<string, number> = {};
  if (prevRankings.length > 0) {
    const prevMap: Record<string, number> = {};
    for (const r of prevRankings) {
      prevMap[r.title] = r.rank;
    }

    // 전날에 없는 작품들 → 과거 전체에서 한 번이라도 있었는지 확인
    const newTitles = rankings
      .filter((r) => !(r.title in prevMap))
      .map((r) => r.title);

    let everSeenSet = new Set<string>();
    if (newTitles.length > 0) {
      const everSeenRows = await sql`
        SELECT DISTINCT title FROM rankings
        WHERE platform = ${platform} AND title = ANY(${newTitles})
          AND date < ${date}
      `;
      everSeenSet = new Set(everSeenRows.map((r) => r.title));
    }

    for (const r of rankings) {
      if (r.title in prevMap) {
        rankChanges[r.title] = prevMap[r.title] - r.rank;
      } else if (everSeenSet.has(r.title)) {
        rankChanges[r.title] = 998; // 재진입
      } else {
        rankChanges[r.title] = 999; // NEW (첫 등장)
      }
    }
  }

  // thumbnails + unified_work_id map
  const thumbnails: Record<string, string> = {};
  const unifiedIds: Record<string, number> = {};
  const publishers: Record<string, string> = {};
  const genres: Record<string, string> = {};
  const genreKrs: Record<string, string> = {};
  for (const t of thumbRows) {
    if (t.thumbnail_url || t.thumbnail_base64) {
      thumbnails[t.title] = String(t.thumbnail_url || t.thumbnail_base64);
    }
    if (t.unified_work_id) {
      unifiedIds[t.title] = t.unified_work_id;
    }
    if (t.publisher) {
      publishers[t.title] = t.publisher;
    }
    // 장르쌍은 단일 소스에서만 사용: works 에 genre/genre_kr 중 하나라도 있으면
    // works 쌍만, 둘 다 없을 때만 검증된 unified 쌍 (소스 섞기 방지)
    const useWorksPair = Boolean(t.w_genre || t.w_genre_kr);
    const genre = useWorksPair ? t.w_genre : t.u_genre;
    const genreKr = useWorksPair ? t.w_genre_kr : t.u_genre_kr;
    if (genre) {
      genres[t.title] = genre;
    }
    if (genreKr) {
      genreKrs[t.title] = genreKr;
    }
  }

  // 매칭 안된 제목 → prefix LIKE + 정규화 매칭 (대소문자/하이픈/아포스트로피 차이 대응)
  const missingTitles = titles.filter((t) => !thumbnails[t]);
  if (missingTitles.length > 0) {
    // normalize: 소문자 + 영숫자만
    const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, "");

    // 퍼지 매칭은 썸네일 전용.
    // unified_work_id/publisher/genre/genre_kr 은 오매칭 시 잘못된 작품에 연결될 수 있어
    // 정확 매칭에서만 전파한다.
    // 정규화 비교는 비라틴 제목이 norm=='' 이 되어 서로 오매칭되는 것을 막기 위해
    // 정규화 결과가 비어 있지 않을 때만 허용한다.
    const fallbackRows = await sql`
      SELECT w.title AS full_title, w.thumbnail_url, w.thumbnail_base64
      FROM works w
      WHERE w.platform = ${platform}
        AND EXISTS (
          SELECT 1 FROM unnest(${missingTitles}::text[]) AS t(short)
          WHERE w.title LIKE t.short || '%'
             OR t.short LIKE w.title || '%'
             OR (
               LOWER(REGEXP_REPLACE(w.title, '[^a-zA-Z0-9]', '', 'g')) <> ''
               AND LOWER(REGEXP_REPLACE(t.short, '[^a-zA-Z0-9]', '', 'g')) <> ''
               AND (
                 LOWER(REGEXP_REPLACE(w.title, '[^a-zA-Z0-9]', '', 'g'))
                    = LOWER(REGEXP_REPLACE(t.short, '[^a-zA-Z0-9]', '', 'g'))
                 OR LEFT(LOWER(REGEXP_REPLACE(w.title, '[^a-zA-Z0-9]', '', 'g')), 20)
                    = LEFT(LOWER(REGEXP_REPLACE(t.short, '[^a-zA-Z0-9]', '', 'g')), 20)
               )
             )
        )
    `;
    for (const fb of fallbackRows) {
      const nfb = norm(fb.full_title);
      const matchedShort = missingTitles.find((t) => {
        const nt = norm(t);
        return fb.full_title.startsWith(t) || t.startsWith(fb.full_title)
          || (nfb !== "" && nt !== ""
            && (nfb === nt || nfb.slice(0, 20) === nt.slice(0, 20)));
      });
      if (matchedShort) {
        const fallbackThumbnail = fb.thumbnail_url || fb.thumbnail_base64;
        if (fallbackThumbnail && !thumbnails[matchedShort]) {
          thumbnails[matchedShort] = String(fallbackThumbnail);
        }
      }
    }
  }

  const result = rankings.map((r) => {
    // 장르쌍 혼합 방지: rankings 에 genre/genre_kr 중 하나라도 있으면 rankings 값만
    // 사용하고, 둘 다 비어 있을 때만 works 소스의 쌍을 사용한다.
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
      thumbnail_url: thumbnails[r.title] || null,
      unified_work_id: unifiedIds[r.title] || null,
      publisher: publishers[r.title] || null,
    };
  });

  return NextResponse.json(result, {
    headers: {
      "Cache-Control": "public, s-maxage=300, stale-while-revalidate=600",
    },
  });
}
