"use client";

import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Header } from "@/components/header";
import { DateSelector } from "@/components/date-selector";
import { PlatformTabs } from "@/components/platform-tabs";
import { GenrePills } from "@/components/genre-pills";
import { RankingTable } from "@/components/ranking-table";
import { Checkbox } from "@/components/ui/checkbox";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { getPlatformById } from "@/lib/constants";
import { contentSwap } from "@/lib/motion";
import type { Ranking, PlatformStats } from "@/lib/types";
import type { TrendReport } from "@/lib/trend-report";
import { TrendReportCard } from "@/components/trend-report";
import { RiversePeriodReport } from "@/components/riverse-period-report";

interface DashboardClientProps {
  initialDates: string[];
  initialDate: string;
  initialLastUpdated?: Record<string, string>;
  initialStats: Record<string, PlatformStats>;
  initialRiverseCounts: Record<string, number>;
  initialRankings: Ranking[];
  initialPlatform: string;
  trendReport?: TrendReport | null;
}

export function DashboardClient({
  initialDates,
  initialDate,
  initialLastUpdated,
  initialStats,
  initialRiverseCounts,
  initialRankings,
  initialPlatform,
  trendReport,
}: DashboardClientProps) {
  const [dates] = useState<string[]>(initialDates);
  const [selectedDate, setSelectedDate] = useState(initialDate);
  const [selectedPlatform, setSelectedPlatform] = useState(initialPlatform);
  const [selectedGenre, setSelectedGenre] = useState("");
  const [rankings, setRankings] = useState<Ranking[]>(initialRankings);
  const [stats, setStats] = useState<Record<string, PlatformStats>>(initialStats);
  const [riverseCounts, setRiverseCounts] = useState<Record<string, number>>(initialRiverseCounts);
  const [riverseOnly, setRiverseOnly] = useState(false);
  const [loading, setLoading] = useState(false);

  const isInitialState = selectedDate === initialDate && selectedPlatform === initialPlatform && selectedGenre === "";

  useEffect(() => {
    if (selectedDate === initialDate) {
      setStats(initialStats);
      return;
    }
    fetch(`/api/stats?date=${selectedDate}`)
      .then((res) => res.json())
      .then(setStats);
  }, [selectedDate, initialDate, initialStats]);

  useEffect(() => {
    if (selectedDate === initialDate && selectedPlatform === initialPlatform) {
      setRiverseCounts(initialRiverseCounts);
      return;
    }
    fetch(`/api/riverse-counts?date=${selectedDate}&platform=${selectedPlatform}`)
      .then((res) => res.json())
      .then(setRiverseCounts);
  }, [selectedDate, selectedPlatform, initialDate, initialPlatform, initialRiverseCounts]);

  useEffect(() => {
    if (isInitialState) {
      setRankings(initialRankings);
      setLoading(false);
      return;
    }
    if (!selectedDate || !selectedPlatform) return;
    setLoading(true);
    const params = new URLSearchParams({
      date: selectedDate,
      platform: selectedPlatform,
      sub_category: selectedGenre,
    });
    fetch(`/api/rankings?${params}`)
      .then((res) => res.json())
      .then((data: Ranking[]) => {
        setRankings(data);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [selectedDate, selectedPlatform, selectedGenre, isInitialState, initialRankings]);

  const handlePlatformChange = (id: string) => {
    setSelectedPlatform(id);
    const pInfo = getPlatformById(id);
    const firstGenreKey = pInfo?.genres[0]?.key ?? "";
    setSelectedGenre(firstGenreKey);
    setRiverseOnly(false);
  };

  const platform = getPlatformById(selectedPlatform);
  const platformColor = platform?.color || "#0D3B70";

  const displayRankings = riverseOnly
    ? rankings.filter((r) => r.is_riverse)
    : rankings;

  const sourceUrl = platform?.sourceUrl || "";

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-[1200px] mx-auto px-3 sm:px-6">
        {/* CSS 애니메이션: 페이지 로드 시 순차 등장 */}
        <div className="anim-section" style={{ animationDelay: "0ms" }}>
          <Header />
        </div>

        <div className="anim-section mt-4" style={{ animationDelay: "60ms" }}>
          <TrendReportCard report={trendReport} />
        </div>

        <div className="anim-section mt-3" style={{ animationDelay: "90ms" }}>
          <RiversePeriodReport />
        </div>

        <div className="anim-section flex items-center justify-between mt-4 mb-3" style={{ animationDelay: "120ms" }}>
          <div className="flex items-center gap-3">
            <DateSelector
              dates={dates}
              selected={selectedDate}
              onSelect={setSelectedDate}
            />
            {initialLastUpdated?.[selectedDate] && (
              <span className="text-[11px] text-muted-foreground">
                최종 수집: {new Date(initialLastUpdated[selectedDate]).toLocaleString("ko-KR", { timeZone: "Asia/Tokyo", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })}
              </span>
            )}
          </div>
          {sourceUrl && (
            <a
              href={sourceUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              📎 데이터 출처: {platform?.name}
            </a>
          )}
        </div>

        <div className="anim-section" style={{ animationDelay: "180ms" }}>
          <PlatformTabs
            selected={selectedPlatform}
            onSelect={handlePlatformChange}
            stats={stats}
          />
        </div>

        {platform && platform.genres.length > 1 && (
          <div className="anim-section mt-3" style={{ animationDelay: "240ms" }}>
            <GenrePills
              genres={platform.genres}
              selected={selectedGenre}
              onSelect={setSelectedGenre}
              platformColor={platformColor}
              riverseCounts={riverseCounts}
            />
          </div>
        )}

        <div className="anim-section flex items-center justify-between mt-4 mb-2" style={{ animationDelay: "300ms" }}>
          <div className="text-sm font-medium text-foreground">
            <span className="font-bold" style={{ color: platformColor }}>
              {platform?.name}
            </span>
            {selectedGenre && platform && (
              <span className="text-muted-foreground ml-1">
                [{platform.genres.find((g) => g.key === selectedGenre)?.label}]
              </span>
            )}
            <span className="text-muted-foreground ml-2">
              TOP {displayRankings.length} — {selectedDate}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <Checkbox
              id="riverse-filter"
              checked={riverseOnly}
              onCheckedChange={(v) => setRiverseOnly(v === true)}
            />
            <label
              htmlFor="riverse-filter"
              className="text-sm text-muted-foreground cursor-pointer select-none"
            >
              리버스 작품만
            </label>
          </div>
        </div>

        {/* 콘텐츠 전환: framer-motion AnimatePresence */}
        <AnimatePresence mode="wait">
          {loading ? (
            <motion.div
              key="skeleton"
              variants={contentSwap}
              initial="enter"
              animate="center"
              exit="exit"
              className="space-y-3 mt-4"
            >
              {Array.from({ length: 10 }).map((_, i) => (
                <Skeleton key={i} className="h-[72px] w-full rounded-lg" />
              ))}
            </motion.div>
          ) : (
            <motion.div
              key={`table-${selectedPlatform}-${selectedGenre}`}
              variants={contentSwap}
              initial="enter"
              animate="center"
              exit="exit"
            >
              <RankingTable
                rankings={displayRankings}
                platformColor={platformColor}
                platform={selectedPlatform}
              />
            </motion.div>
          )}
        </AnimatePresence>

        <Separator className="mt-8" />
        <footer className="py-4 text-center text-xs text-muted-foreground">
          RIVERSE Inc. | 데이터: Supabase PostgreSQL | 매일 자동 수집
        </footer>
      </div>
    </div>
  );
}
