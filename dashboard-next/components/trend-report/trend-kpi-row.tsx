"use client";

import type { KpiMetrics } from "@/lib/trend-report";

// ─── 리버스 네이비 팔레트 ─────────────────────────────
const RV = "#0D3B70";
const RV_MID = "#1A5296";
const RV_LIGHT = "#E8EEF5";
const UP_COLOR = "#1B7A6E";   // 청록 (상승 — 차분하지만 구분 가능)
const DOWN_COLOR = "#A34D5E"; // 로즈 그레이 (하락 — 차분한 붉은 톤)

// ─── SVG 아이콘 (네이비 모노톤) ──────────────────────
function IconRankings() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
      <path d="M2 12h3v3H2zM6.5 8H10v7H6.5zM11 4h3v11h-3z" fill={RV_MID} opacity="0.7" />
      <path d="M11 4h3v11h-3z" fill={RV_MID} />
    </svg>
  );
}

function IconTarget() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
      <circle cx="8" cy="8" r="6.5" stroke={RV_MID} strokeWidth="1.5" />
      <circle cx="8" cy="8" r="3.5" stroke={RV_MID} strokeWidth="1.5" />
      <circle cx="8" cy="8" r="1" fill={RV_MID} />
    </svg>
  );
}

function IconTrophy() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
      <path d="M5 2h6v5a3 3 0 01-6 0V2z" stroke={RV_MID} strokeWidth="1.5" />
      <path d="M5 4H3a2 2 0 000 4h1M11 4h2a2 2 0 010 4h-1" stroke={RV_MID} strokeWidth="1.2" />
      <path d="M6.5 11h3v1.5h-3z" fill={RV_MID} />
      <path d="M5 13.5h6" stroke={RV_MID} strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function IconShare() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
      <rect x="2" y="2" width="12" height="12" rx="2" stroke={RV_MID} strokeWidth="1.5" />
      <path d="M2 8h5v6H2z" fill={RV_MID} opacity="0.5" />
      <path d="M7 5h7v9H7z" fill={RV_MID} opacity="0.8" />
    </svg>
  );
}

// ─── Components ──────────────────────────────────────

function DeltaIndicator({ value, inverted = false }: { value: number; inverted?: boolean }) {
  if (value === 0) return <span className="text-xs font-medium" style={{ color: `${RV}60` }}>—</span>;

  const isGood = inverted ? value < 0 : value > 0;
  const displayValue = Math.abs(value);
  const arrow = isGood ? "▲" : "▼";
  const color = isGood ? UP_COLOR : DOWN_COLOR;

  return (
    <span className="inline-flex items-center gap-0.5 text-xs font-bold" style={{ color }}>
      {arrow} {displayValue % 1 !== 0 ? displayValue.toFixed(1) : displayValue}
    </span>
  );
}

interface KpiCardProps {
  label: string;
  value: number;
  unit?: string;
  delta: number;
  inverted?: boolean;
  icon: React.ReactNode;
}

function KpiCard({ label, value, unit = "", delta, inverted = false, icon }: KpiCardProps) {
  return (
    <div
      className="relative overflow-hidden rounded-xl p-3 sm:p-4 transition-shadow hover:shadow-md"
      style={{
        backgroundColor: "var(--card)",
        border: `1px solid ${RV}15`,
        boxShadow: `0 1px 3px ${RV}08`,
      }}
    >
      {/* 상단 네이비 악센트 라인 */}
      <div
        className="absolute top-0 left-0 right-0 h-[2px]"
        style={{ background: `linear-gradient(90deg, ${RV}, ${RV_MID})` }}
      />
      <div className="flex items-center gap-1.5 mb-1.5">
        {icon}
        <span className="text-[11px] font-medium" style={{ color: `${RV}99` }}>{label}</span>
      </div>
      <div className="flex items-baseline gap-2">
        <span className="text-xl sm:text-2xl font-bold" style={{ color: RV }}>
          {value % 1 !== 0 ? value.toFixed(1) : value}
          {unit && <span className="text-sm font-normal ml-0.5">{unit}</span>}
        </span>
        <DeltaIndicator value={delta} inverted={inverted} />
      </div>
      <div className="text-[10px] mt-0.5" style={{ color: `${RV}50` }}>vs 7일 전</div>
    </div>
  );
}

export function TrendKpiRow({ kpi }: { kpi: KpiMetrics }) {
  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-2 sm:gap-3">
      <KpiCard
        label="랭킹 진입 수"
        value={kpi.riverse_in_rankings}
        unit="건"
        delta={kpi.riverse_in_rankings_delta}
        icon={<IconRankings />}
      />
      <KpiCard
        label="평균 순위"
        value={kpi.riverse_avg_rank}
        unit="위"
        delta={kpi.riverse_avg_rank_delta}
        inverted
        icon={<IconTarget />}
      />
      <KpiCard
        label="TOP 3 수"
        value={kpi.riverse_top3_count}
        unit="건"
        delta={kpi.riverse_top3_delta}
        icon={<IconTrophy />}
      />
      <KpiCard
        label="전체 점유율"
        value={kpi.riverse_share_pct}
        unit="%"
        delta={kpi.riverse_share_pct_delta}
        icon={<IconShare />}
      />
    </div>
  );
}
