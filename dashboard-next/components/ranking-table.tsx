"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import Link from "next/link";
import { RankBadge } from "./rank-badge";
import { RankChange } from "./rank-change";
import { RiverseBadge } from "./riverse-badge";
import { tableContainer, tableRowVariant } from "@/lib/motion";
import type { Ranking } from "@/lib/types";

interface RankingTableProps {
  rankings: Ranking[];
  platformColor: string;
  platform: string;
}

function Thumbnail({
  ranking,
  platform,
}: {
  ranking: Ranking;
  platform: string;
}) {
  const cdnUrl = ranking.thumbnail_url;
  const proxyUrl = `/api/thumbnail?platform=${encodeURIComponent(platform)}&title=${encodeURIComponent(ranking.title)}`;

  const [loadState, setLoadState] = useState<"cdn" | "proxy" | "fallback">(
    cdnUrl ? "cdn" : "proxy"
  );

  if (loadState === "fallback") {
    return (
      <div className="w-[44px] h-[62px] bg-muted rounded flex items-center justify-center text-lg shrink-0">
        📖
      </div>
    );
  }

  const src = loadState === "cdn" ? cdnUrl! : proxyUrl;

  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={src}
      alt=""
      width={44}
      height={62}
      className="rounded shadow-sm bg-muted shrink-0"
      style={{ width: 44, height: 62, objectFit: "cover" }}
      loading={src.startsWith("data:") ? "eager" : "lazy"}
      referrerPolicy="no-referrer"
      onError={() => {
        if (loadState === "cdn") {
          setLoadState("proxy");
        } else {
          setLoadState("fallback");
        }
      }}
    />
  );
}

type SortKey = "rank" | "publisher";
type SortDir = "asc" | "desc";

export function RankingTable({
  rankings,
  platformColor,
  platform,
}: RankingTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>("rank");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [publisherFilter, setPublisherFilter] = useState<string>("");

  if (rankings.length === 0) {
    if (platform === "linemanga_app") {
      return (
        <div className="my-8 mx-auto max-w-2xl rounded-lg border border-border bg-muted/40 px-6 py-8 text-center">
          <div className="text-2xl mb-3">⚠️</div>
          <div className="text-sm font-semibold text-foreground mb-2">
            라인망가 앱 순위 수집 중단
          </div>
          <div className="text-xs text-muted-foreground leading-relaxed">
            라인망가 앱의 자동화 차단 정책(Debugging Mode Detected)으로
            <br />
            당분간 라인망가 앱 순위는 수집할 수 없습니다.
            <br />
            <span className="text-muted-foreground/70 mt-2 inline-block">
              이전에 수집된 날짜의 데이터는 정상 조회 가능합니다.
            </span>
          </div>
        </div>
      );
    }
    return (
      <div className="text-center py-12 text-muted-foreground">
        데이터가 없습니다.
      </div>
    );
  }

  // 제작사 목록 (작품 수 순)
  const publisherCounts: Record<string, number> = {};
  for (const r of rankings) {
    if (r.publisher) {
      publisherCounts[r.publisher] = (publisherCounts[r.publisher] || 0) + 1;
    }
  }
  const publisherOptions = Object.entries(publisherCounts)
    .sort((a, b) => b[1] - a[1])
    .map(([name, count]) => ({ name, count }));

  const filtered = publisherFilter
    ? rankings.filter((r) => r.publisher === publisherFilter)
    : rankings;

  const sorted = [...filtered].sort((a, b) => {
    if (sortKey === "rank") {
      return sortDir === "asc" ? a.rank - b.rank : b.rank - a.rank;
    }
    // publisher sort
    const pa = a.publisher || "";
    const pb = b.publisher || "";
    if (!pa && !pb) return a.rank - b.rank;
    if (!pa) return 1;
    if (!pb) return -1;
    const cmp = pa.localeCompare(pb, "ja");
    return sortDir === "asc" ? cmp || a.rank - b.rank : -cmp || a.rank - b.rank;
  });

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  };

  return (
    <div className="w-full">
      <table
        className="w-full text-sm border-collapse"
        style={{ tableLayout: "fixed" }}
      >
        <thead>
          <tr className="bg-muted/50 border-b">
            <th
              style={{ width: 50 }}
              className="h-10 px-2 text-center font-medium text-foreground"
            >
              순위
            </th>
            <th
              style={{ width: 56 }}
              className="h-10 px-1 font-medium"
            ></th>
            <th
              style={{ width: 60 }}
              className="h-10 px-2 text-center font-medium text-foreground"
            >
              변동
            </th>
            <th className="h-10 px-2 text-left font-medium text-foreground">
              작품명
            </th>
            <th
              style={{ width: 180 }}
              className="h-10 px-2 text-left font-medium text-foreground hidden md:table-cell"
            >
              <select
                value={publisherFilter}
                onChange={(e) => setPublisherFilter(e.target.value)}
                className="text-xs font-medium bg-transparent border-none outline-none cursor-pointer text-foreground w-full truncate"
              >
                <option value="">제작사</option>
                {publisherOptions.map(({ name, count }) => (
                  <option key={name} value={name}>
                    {name} ({count})
                  </option>
                ))}
              </select>
            </th>
            <th
              style={{ width: 100 }}
              className="h-10 px-2 text-left font-medium text-foreground hidden md:table-cell"
            >
              장르
            </th>
          </tr>
        </thead>
        <motion.tbody
          variants={tableContainer}
          initial="hidden"
          animate="show"
        >
          {sorted.map((r) => (
            <motion.tr
              key={r.rank}
              variants={tableRowVariant}
              className="border-b hover:bg-muted/30 transition-colors"
            >
              {/* 순위 */}
              <td className="py-2 px-2 text-center align-middle">
                <RankBadge rank={r.rank} platformColor={platformColor} />
              </td>

              {/* 썸네일 */}
              <td className="py-2 px-1 align-middle">
                <Thumbnail ranking={r} platform={platform} />
              </td>

              {/* 변동 */}
              <td className="py-2 px-2 text-center align-middle">
                <RankChange change={r.rank_change} />
              </td>

              {/* 작품명 + 한국어 제목 */}
              <td className="py-2 px-2 align-middle overflow-hidden">
                <div className="truncate">
                  <Link
                    href={r.unified_work_id ? `/work/${r.unified_work_id}` : `/title/${platform}/${encodeURIComponent(r.title)}`}
                    target="_blank"
                    className="font-medium text-foreground hover:underline"
                    style={{ textDecorationColor: platformColor }}
                  >
                    {r.title}
                  </Link>
                  {r.is_riverse && <RiverseBadge />}
                  {r.url && (
                    <a
                      href={r.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="ml-1 text-xs text-muted-foreground hover:text-foreground"
                      title="원본 페이지"
                    >
                      🔗
                    </a>
                  )}
                </div>
                {/* 한국어 제목 (작은 글씨) - 전 플랫폼 동일 */}
                {r.title_kr && (
                  <div className="mt-0.5 truncate">
                    <span className="text-xs text-muted-foreground">
                      {r.title_kr}
                    </span>
                  </div>
                )}
                {/* 모바일: 장르 + 제작사 인라인 */}
                <div className="md:hidden mt-0.5 truncate">
                  {(r.genre_kr || r.genre) && (
                    <span className="text-[10px] bg-muted text-muted-foreground px-1.5 py-0.5 rounded-full">
                      {r.genre_kr || r.genre}
                    </span>
                  )}
                  {r.publisher && (
                    <span className="ml-1 text-[10px] text-muted-foreground/70">
                      {r.publisher}
                    </span>
                  )}
                </div>
              </td>

              {/* 제작사 */}
              <td className="py-2 px-2 align-middle text-muted-foreground text-sm hidden md:table-cell overflow-hidden">
                <div className="truncate">{r.publisher || ""}</div>
              </td>

              {/* 장르 */}
              <td className="py-2 px-2 align-middle hidden md:table-cell">
                {(r.genre_kr || r.genre) && (
                  <span className="bg-muted text-muted-foreground px-2 py-0.5 rounded-full text-xs whitespace-nowrap">
                    {r.genre_kr || r.genre}
                  </span>
                )}
              </td>

            </motion.tr>
          ))}
        </motion.tbody>
      </table>
    </div>
  );
}
