"use client";

import Image from "next/image";
import { motion } from "framer-motion";
import { cn } from "@/lib/utils";
import { PLATFORMS } from "@/lib/constants";
import type { PlatformStats } from "@/lib/types";

interface PlatformTabsProps {
  selected: string;
  onSelect: (id: string) => void;
  stats: Record<string, PlatformStats>;
}

export function PlatformTabs({ selected, onSelect, stats }: PlatformTabsProps) {
  return (
    <div className="grid grid-cols-5 sm:grid-cols-8 xl:grid-cols-[repeat(16,minmax(0,1fr))] gap-1.5 sm:gap-2 justify-items-center mx-auto max-w-4xl xl:max-w-none">
      {PLATFORMS.map((p) => {
        const isActive = selected === p.id;
        return (
          <motion.button
            key={p.id}
            onClick={() => onSelect(p.id)}
            title={p.name}
            className={cn(
              "relative rounded-xl p-1 sm:p-1.5 cursor-pointer w-full max-w-[60px]",
              "border-2",
              isActive
                ? "shadow-lg"
                : "border-transparent bg-white hover:bg-muted"
            )}
            style={
              isActive
                ? {
                    borderColor: p.color,
                    backgroundColor: p.color + "12",
                  }
                : undefined
            }
            whileHover={{ scale: 1.08 }}
            whileTap={{ scale: 0.95 }}
            transition={{ type: "spring", stiffness: 400, damping: 25 }}
          >
            {isActive && (
              <motion.div
                layoutId="platform-active-indicator"
                className="absolute inset-0 rounded-xl"
                style={{ boxShadow: `0 4px 16px ${p.color}40` }}
                transition={{ type: "spring", stiffness: 350, damping: 30 }}
              />
            )}
            {p.logo ? (
              <div className="relative z-10 flex items-center justify-center">
                <Image
                  src={p.logo}
                  alt={p.name}
                  width={48}
                  height={48}
                  className="rounded-lg object-contain w-9 h-9 sm:w-11 sm:h-11"
                />
                {p.badge && (
                  <span
                    className="absolute -bottom-1 -right-1 px-0.5 sm:px-1 py-px rounded text-[7px] sm:text-[8px] font-bold text-white leading-none"
                    style={{ backgroundColor: p.color }}
                  >
                    {p.badge}
                  </span>
                )}
              </div>
            ) : (
              <div
                className="relative z-10 rounded-lg w-9 h-9 sm:w-11 sm:h-11 flex items-center justify-center text-white font-bold text-base sm:text-lg"
                style={{ backgroundColor: p.color }}
              >
                {p.name.charAt(0)}
              </div>
            )}
          </motion.button>
        );
      })}
    </div>
  );
}
