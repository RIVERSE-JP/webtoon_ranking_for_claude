"use client";

import { useState, useEffect, useMemo } from "react";
import Link from "next/link";
import { getPlatformById } from "@/lib/constants";

// ─── 리버스 네이비 팔레트 ─────────────────────────────
const RV = "#0D3B70";
const RV_MID = "#1A5296";
const RV_LIGHT = "#E8EEF5";

// ─── 타입 ───────────────────────────────────────────
interface PlatformWork {
  title: string;
  title_kr: string | null;
  platform: string;
  unified_work_id: number | null;
  rank1_count: number;
  rank2_count: number;
  rank3_count: number;
  top3_count: number;
  top10_count: number;
  total_appearances: number;
  days_ranked: number;
  best_rank: number;
  avg_rank: number;
}

interface UnifiedWork extends Omit<PlatformWork, "platform"> {
  platforms: string;
  platform_count: number;
}

interface AnalysisResponse {
  summary: {
    total_days: number;
    unique_works: number;
    works_with_rank1: number;
    works_with_top3: number;
    works_with_top10: number;
    total_appearances: number;
  };
  works: PlatformWork[] | UnifiedWork[];
  mode: "platform" | "unified";
  scope: "main" | "all";
  start: string;
  end: string;
}

type SortKey = "rank1" | "top3" | "top10" | "total" | "best" | "avg";

// ─── Helpers ─────────────────────────────────────────
function isoNDaysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

function PlatformBadge({ platform }: { platform: string }) {
  const info = getPlatformById(platform);
  return (
    <span
      className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold text-white shrink-0"
      style={{ backgroundColor: info?.color ?? "#666" }}
    >
      {info?.name ?? platform}
    </span>
  );
}

function WorkLink({
  unifiedWorkId,
  children,
}: {
  unifiedWorkId: number | null;
  children: React.ReactNode;
}) {
  if (unifiedWorkId) {
    return (
      <Link
        href={`/work/${unifiedWorkId}`}
        className="hover:underline transition-colors"
        style={{ color: RV }}
      >
        {children}
      </Link>
    );
  }
  return <span style={{ color: RV }}>{children}</span>;
}

function ToggleGroup<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div
      className="inline-flex rounded-lg p-0.5"
      style={{ backgroundColor: RV_LIGHT }}
    >
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => onChange(opt.value)}
          className="px-2.5 py-1 text-[11px] font-medium rounded-md transition-colors cursor-pointer"
          style={
            value === opt.value
              ? { backgroundColor: RV, color: "#fff" }
              : { color: RV_MID }
          }
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

// ─── 메인 컴포넌트 ────────────────────────────────────
export function RiversePeriodReport() {
  const [open, setOpen] = useState(false);
  const [start, setStart] = useState(isoNDaysAgo(7));
  const [end, setEnd] = useState(isoNDaysAgo(0));
  const [mode, setMode] = useState<"platform" | "unified">("platform");
  const [scope, setScope] = useState<"main" | "all">("main");
  const [sortBy, setSortBy] = useState<SortKey>("top3");
  const [data, setData] = useState<AnalysisResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 데이터 로드
  useEffect(() => {
    if (!open) return;
    setLoading(true);
    setError(null);
    const url = `/api/riverse-period-analysis?start=${start}&end=${end}&mode=${mode}&scope=${scope}`;
    fetch(url)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((d: AnalysisResponse) => setData(d))
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [open, start, end, mode, scope]);

  // 정렬
  const sortedWorks = useMemo(() => {
    if (!data?.works) return [];
    const arr = [...data.works];
    arr.sort((a, b) => {
      switch (sortBy) {
        case "rank1":
          return b.rank1_count - a.rank1_count || b.top3_count - a.top3_count;
        case "top3":
          return b.top3_count - a.top3_count || b.rank1_count - a.rank1_count;
        case "top10":
          return b.top10_count - a.top10_count;
        case "total":
          return b.total_appearances - a.total_appearances;
        case "best":
          return a.best_rank - b.best_rank;
        case "avg":
          return a.avg_rank - b.avg_rank;
      }
    });
    return arr;
  }, [data, sortBy]);

  // 빠른 기간 프리셋
  const setPreset = (days: number) => {
    setStart(isoNDaysAgo(days));
    setEnd(isoNDaysAgo(0));
  };

  return (
    <div
      className="relative overflow-hidden rounded-xl bg-card shadow-sm"
      style={{ border: `1px solid ${RV}22` }}
    >
      {/* 헤더 */}
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-4 py-3 cursor-pointer transition-colors hover:bg-muted/30"
        style={{ borderBottom: open ? `1px solid ${RV}15` : "none" }}
      >
        <div className="flex items-center gap-2">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path
              d="M2 13V3M2 13h12M2 8l3-2 3 1 4-3"
              stroke={RV}
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            <circle cx="11" cy="4" r="1.2" fill={RV} />
          </svg>
          <h3 className="text-sm font-bold" style={{ color: RV }}>
            리버스 작품 기간별 랭크인 분석
          </h3>
        </div>
        <span
          className="inline-flex items-center justify-center w-5 h-5 rounded-full"
          style={{ backgroundColor: RV_LIGHT }}
        >
          <svg
            width="10"
            height="10"
            viewBox="0 0 10 10"
            className={`transition-transform duration-200 ${open ? "rotate-180" : ""}`}
          >
            <path
              d="M1 3.5L5 7.5L9 3.5"
              stroke={RV_MID}
              strokeWidth="1.5"
              fill="none"
              strokeLinecap="round"
            />
          </svg>
        </span>
      </button>

      {open && (
        <div className="p-4 space-y-4 animate-in fade-in slide-in-from-top-2 duration-200">
          {/* 컨트롤 */}
          <div className="flex flex-wrap items-center gap-3">
            {/* 날짜 범위 */}
            <div className="flex items-center gap-1.5">
              <input
                type="date"
                value={start}
                max={end}
                onChange={(e) => setStart(e.target.value)}
                className="px-2 py-1 text-xs rounded border"
                style={{ borderColor: `${RV}33`, color: RV }}
              />
              <span className="text-xs" style={{ color: `${RV}80` }}>
                ~
              </span>
              <input
                type="date"
                value={end}
                min={start}
                onChange={(e) => setEnd(e.target.value)}
                className="px-2 py-1 text-xs rounded border"
                style={{ borderColor: `${RV}33`, color: RV }}
              />
            </div>

            {/* 빠른 프리셋 */}
            <div className="flex gap-1">
              {[
                { d: 7, l: "7일" },
                { d: 14, l: "14일" },
                { d: 30, l: "30일" },
                { d: 90, l: "90일" },
              ].map((p) => (
                <button
                  key={p.d}
                  type="button"
                  onClick={() => setPreset(p.d)}
                  className="px-2 py-1 text-[11px] rounded transition-colors cursor-pointer"
                  style={{
                    backgroundColor: RV_LIGHT,
                    color: RV_MID,
                  }}
                >
                  {p.l}
                </button>
              ))}
            </div>

            {/* 집계 모드 */}
            <ToggleGroup
              value={mode}
              onChange={setMode}
              options={[
                { value: "platform", label: "플랫폼별" },
                { value: "unified", label: "작품 통합" },
              ]}
            />

            {/* 카테고리 범위 */}
            <ToggleGroup
              value={scope}
              onChange={setScope}
              options={[
                { value: "main", label: "총합 카테고리" },
                { value: "all", label: "모든 장르" },
              ]}
            />
          </div>

          {/* 요약 KPI */}
          {data && !loading && (
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
              <SummaryCell label="기간 일수" value={data.summary.total_days} unit="일" />
              <SummaryCell label="고유 작품" value={data.summary.unique_works} unit="개" />
              <SummaryCell label="1위 달성" value={data.summary.works_with_rank1} unit="개" />
              <SummaryCell label="TOP 3 달성" value={data.summary.works_with_top3} unit="개" />
              <SummaryCell label="총 진입 횟수" value={data.summary.total_appearances} unit="회" />
            </div>
          )}

          {/* 로딩/에러 */}
          {loading && (
            <div className="py-8 text-center text-xs" style={{ color: `${RV}80` }}>
              데이터를 불러오는 중...
            </div>
          )}
          {error && (
            <div className="py-4 text-center text-xs text-red-500">에러: {error}</div>
          )}

          {/* 결과 테이블 */}
          {data && !loading && sortedWorks.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr style={{ borderBottom: `1px solid ${RV}22` }}>
                    <th className="text-left py-2 px-2 font-semibold" style={{ color: `${RV}99` }}>
                      #
                    </th>
                    <th className="text-left py-2 px-2 font-semibold" style={{ color: `${RV}99` }}>
                      작품명
                    </th>
                    {mode === "platform" ? (
                      <th className="text-left py-2 px-2 font-semibold" style={{ color: `${RV}99` }}>
                        플랫폼
                      </th>
                    ) : (
                      <th className="text-left py-2 px-2 font-semibold" style={{ color: `${RV}99` }}>
                        플랫폼 수
                      </th>
                    )}
                    <SortableHeader k="rank1" label="🥇 1위" sortBy={sortBy} setSortBy={setSortBy} />
                    <th className="text-right py-2 px-1 font-semibold" style={{ color: `${RV}99` }}>
                      🥈 2위
                    </th>
                    <th className="text-right py-2 px-1 font-semibold" style={{ color: `${RV}99` }}>
                      🥉 3위
                    </th>
                    <SortableHeader k="top3" label="TOP3" sortBy={sortBy} setSortBy={setSortBy} />
                    <SortableHeader k="top10" label="TOP10" sortBy={sortBy} setSortBy={setSortBy} />
                    <SortableHeader k="total" label="총진입" sortBy={sortBy} setSortBy={setSortBy} />
                    <SortableHeader k="best" label="최고" sortBy={sortBy} setSortBy={setSortBy} />
                    <SortableHeader k="avg" label="평균" sortBy={sortBy} setSortBy={setSortBy} />
                  </tr>
                </thead>
                <tbody>
                  {sortedWorks.map((w, i) => (
                    <tr
                      key={`${w.title}-${(w as PlatformWork).platform ?? (w as UnifiedWork).platforms}-${i}`}
                      className="hover:bg-muted/30 transition-colors"
                      style={{ borderBottom: `1px solid ${RV}10` }}
                    >
                      <td className="py-1.5 px-2 font-mono" style={{ color: `${RV}66` }}>
                        {i + 1}
                      </td>
                      <td className="py-1.5 px-2 max-w-[260px]">
                        <WorkLink unifiedWorkId={w.unified_work_id}>
                          <div className="font-medium truncate">{w.title}</div>
                          {w.title_kr && w.title_kr !== w.title && (
                            <div
                              className="text-[10px] truncate"
                              style={{ color: `${RV}60` }}
                            >
                              {w.title_kr}
                            </div>
                          )}
                        </WorkLink>
                      </td>
                      <td className="py-1.5 px-2">
                        {mode === "platform" ? (
                          <PlatformBadge platform={(w as PlatformWork).platform} />
                        ) : (
                          <div className="flex flex-wrap gap-0.5">
                            {(w as UnifiedWork).platforms.split(",").map((p) => (
                              <PlatformBadge key={p} platform={p} />
                            ))}
                          </div>
                        )}
                      </td>
                      <td className="text-right py-1.5 px-1 font-mono font-bold" style={{ color: RV }}>
                        {w.rank1_count || "-"}
                      </td>
                      <td className="text-right py-1.5 px-1 font-mono" style={{ color: `${RV}99` }}>
                        {w.rank2_count || "-"}
                      </td>
                      <td className="text-right py-1.5 px-1 font-mono" style={{ color: `${RV}99` }}>
                        {w.rank3_count || "-"}
                      </td>
                      <td className="text-right py-1.5 px-1 font-mono font-bold" style={{ color: RV }}>
                        {w.top3_count || "-"}
                      </td>
                      <td className="text-right py-1.5 px-1 font-mono" style={{ color: `${RV}99` }}>
                        {w.top10_count || "-"}
                      </td>
                      <td className="text-right py-1.5 px-1 font-mono" style={{ color: `${RV}99` }}>
                        {w.total_appearances}
                      </td>
                      <td className="text-right py-1.5 px-1 font-mono" style={{ color: `${RV}99` }}>
                        #{w.best_rank}
                      </td>
                      <td className="text-right py-1.5 px-1 font-mono" style={{ color: `${RV}99` }}>
                        {w.avg_rank.toFixed(1)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {sortedWorks.length === 200 && (
                <div className="mt-2 text-[10px] text-center" style={{ color: `${RV}60` }}>
                  상위 200개만 표시됩니다. 기간을 좁혀주세요.
                </div>
              )}
            </div>
          )}

          {data && !loading && sortedWorks.length === 0 && (
            <div className="py-8 text-center text-xs" style={{ color: `${RV}80` }}>
              해당 기간에 랭크인한 리버스 작품이 없습니다.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function SummaryCell({ label, value, unit }: { label: string; value: number; unit: string }) {
  return (
    <div
      className="rounded-lg px-3 py-2"
      style={{ backgroundColor: RV_LIGHT }}
    >
      <div className="text-[10px] font-medium" style={{ color: `${RV}99` }}>
        {label}
      </div>
      <div className="text-base font-bold" style={{ color: RV }}>
        {value.toLocaleString()}
        <span className="text-[10px] font-normal ml-0.5">{unit}</span>
      </div>
    </div>
  );
}

function SortableHeader({
  k,
  label,
  sortBy,
  setSortBy,
}: {
  k: SortKey;
  label: string;
  sortBy: SortKey;
  setSortBy: (k: SortKey) => void;
}) {
  const active = sortBy === k;
  return (
    <th
      className="text-right py-2 px-1 font-semibold cursor-pointer select-none"
      style={{ color: active ? RV : `${RV}99` }}
      onClick={() => setSortBy(k)}
    >
      {label} {active && "↓"}
    </th>
  );
}
