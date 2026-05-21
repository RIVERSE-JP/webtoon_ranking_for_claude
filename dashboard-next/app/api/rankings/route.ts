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
          SELECT title, thumbnail_url, thumbnail_base64, unified_work_id, publisher
          FROM works
          WHERE platform = ${platform}
            AND title = ANY(${titles})
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
  }

  // 매칭 안된 제목 → prefix LIKE + 정규화 매칭 (대소문자/하이픈/아포스트로피 차이 대응)
  const missingTitles = titles.filter((t) => !thumbnails[t]);
  if (missingTitles.length > 0) {
    // normalize: 소문자 + 영숫자만
    const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, "");

    const fallbackRows = await sql`
      SELECT w.title AS full_title, w.thumbnail_url, w.thumbnail_base64, w.unified_work_id
      FROM works w
      WHERE w.platform = ${platform}
        AND EXISTS (
          SELECT 1 FROM unnest(${missingTitles}::text[]) AS t(short)
          WHERE w.title LIKE t.short || '%'
             OR t.short LIKE w.title || '%'
             OR LOWER(REGEXP_REPLACE(w.title, '[^a-zA-Z0-9]', '', 'g'))
                = LOWER(REGEXP_REPLACE(t.short, '[^a-zA-Z0-9]', '', 'g'))
             OR LEFT(LOWER(REGEXP_REPLACE(w.title, '[^a-zA-Z0-9]', '', 'g')), 20)
                = LEFT(LOWER(REGEXP_REPLACE(t.short, '[^a-zA-Z0-9]', '', 'g')), 20)
        )
    `;
    for (const fb of fallbackRows) {
      const nfb = norm(fb.full_title);
      const matchedShort = missingTitles.find(
        (t) => fb.full_title.startsWith(t) || t.startsWith(fb.full_title)
          || nfb === norm(t) || nfb.slice(0, 20) === norm(t).slice(0, 20)
      );
      if (matchedShort) {
        const fallbackThumbnail = fb.thumbnail_url || fb.thumbnail_base64;
        if (fallbackThumbnail && !thumbnails[matchedShort]) {
          thumbnails[matchedShort] = String(fallbackThumbnail);
        }
        if (fb.unified_work_id && !unifiedIds[matchedShort]) {
          unifiedIds[matchedShort] = fb.unified_work_id;
        }
      }
    }
  }

  const result = rankings.map((r) => ({
    rank: r.rank,
    title: r.title,
    title_kr: r.title_kr || null,
    genre: r.genre || null,
    genre_kr: r.genre_kr || null,
    url: r.url,
    is_riverse: r.is_riverse,
    rank_change: rankChanges[r.title] ?? 0,
    thumbnail_url: thumbnails[r.title] || null,
    unified_work_id: unifiedIds[r.title] || null,
    publisher: publishers[r.title] || null,
  }));

  return NextResponse.json(result, {
    headers: {
      "Cache-Control": "public, s-maxage=300, stale-while-revalidate=600",
    },
  });
}
