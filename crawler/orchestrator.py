"""
Crawler orchestrator for parallel agent execution.

Manages the lifecycle and coordination of all platform crawler agents.
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, List
from playwright.async_api import async_playwright, Browser

from crawler.agents.base_agent import AgentResult

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('crawler.orchestrator')

# 전체 플랫폼 수 (시모아 어덜트는 코믹시모아에 통합, 라인망가앱 포함)
TOTAL_PLATFORMS = 12


class CrawlerOrchestrator:
    """
    Orchestrates parallel execution of all crawler agents.

    Features:
    - Parallel execution using asyncio.gather()
    - Error isolation (one failure doesn't affect others)
    - Centralized logging and result aggregation
    - Shared browser instance for efficiency
    """

    def __init__(self):
        """Initialize orchestrator."""
        self.date = datetime.now().strftime('%Y-%m-%d')
        self.logger = logger

    async def run_all(self) -> Dict[str, AgentResult]:
        """
        Execute all crawler agents in parallel.

        Returns:
            Dict mapping platform_id to AgentResult
        """
        self.logger.info("=" * 70)
        self.logger.info(f"🚀 일본 웹툰 랭킹 크롤링 시작")
        self.logger.info(f"📅 날짜: {self.date}")
        self.logger.info("=" * 70)

        # Import agents here to avoid circular imports
        from crawler.agents.piccoma_agent import PiccomaAgent
        from crawler.agents.piccoma_manga_agent import PiccomaMangaAgent
        from crawler.agents.linemanga_agent import LinemangaAgent
        from crawler.agents.mechacomic_agent import MechacomicAgent
        from crawler.agents.cmoa_agent import CmoaAgent
        from crawler.agents.comico_agent import ComicoAgent
        from crawler.agents.renta_agent import RentaAgent
        from crawler.agents.booklive_agent import BookliveAgent
        from crawler.agents.ebookjapan_agent import EbookjapanAgent
        from crawler.agents.lezhin_agent import LezhinAgent
        from crawler.agents.beltoon_agent import BeltoonAgent
        from crawler.agents.unext_agent import UnextAgent
        from crawler.agents.unext_free_agent import UnextFreeAgent
        from crawler.agents.kmanga_agent import KmangaAgent
        from crawler.agents.handycomic_agent import HandycomicAgent
        from crawler.agents.linemanga_app_agent import LinemangaAppAgent

        # Create agent instances (12+1 플랫폼, ADB 에이전트 포함)
        agents = [
            # 기존 4개 플랫폼
            PiccomaAgent(),
            PiccomaMangaAgent(),
            LinemangaAgent(),
            MechacomicAgent(),
            CmoaAgent(),
            # 신규 8개 플랫폼
            ComicoAgent(),
            RentaAgent(),
            BookliveAgent(),
            EbookjapanAgent(),
            LezhinAgent(),
            BeltoonAgent(),
            UnextAgent(),
            UnextFreeAgent(),
            KmangaAgent(),
            HandycomicAgent(),
            # ADB 기반 (디바이스 미연결 시 자동 skip)
            # ⚠️ 2026-05-11 비활성화: 라인망가 26.04.22 업데이트로 USB 디버깅 켜진 폰에서
            # 앱 실행 거부 ("Debugging Mode Detected"). ADB 크롤링 영구 차단됨.
            # 재개하려면 우회 방법(별도 폰 + 루팅 등) 마련 후 아래 주석 해제.
            # LinemangaAppAgent(),
        ]

        total = len(agents)

        # Execute all agents in parallel (각 에이전트가 자체 브라우저 생성)
        self.logger.info(f"Starting parallel execution of {total} agents...")

        results = await asyncio.gather(
            *[self._run_agent_with_browser(agent) for agent in agents],
            return_exceptions=True
        )

        # Process results
        results_dict = {}
        success_count = 0
        fail_count = 0

        for result in results:
            if isinstance(result, Exception):
                self.logger.error(f"Unexpected error: {result}")
                continue

            results_dict[result.platform] = result

            if result.success:
                success_count += 1
            else:
                fail_count += 1

        # Print summary
        self.logger.info("")
        self.logger.info("=" * 70)
        self.logger.info("✅ 크롤링 완료")
        self.logger.info("=" * 70)
        self.logger.info(f"📊 성공: {success_count}/{total}개 플랫폼")
        self.logger.info(f"❌ 실패: {fail_count}/{total}개 플랫폼")
        self.logger.info("")

        # Print detailed results
        for platform_id, result in results_dict.items():
            if result.success:
                self.logger.info(f"   ✅ {platform_id}: {result.count}개 작품")
            else:
                self.logger.info(f"   ❌ {platform_id}: {result.error}")

        # Print summary statistics
        total_items = sum(r.count for r in results_dict.values() if r.success)
        self.logger.info("")
        self.logger.info(f"📚 총 {total_items}개 작품 수집")
        self.logger.info(f"💾 데이터 저장: Supabase PostgreSQL")
        self.logger.info(f"📦 백업: data/backup/{self.date}/")
        self.logger.info("=" * 70)

        if fail_count > 0:
            self.logger.warning(f"⚠️  일부 플랫폼 크롤링 실패 ({success_count}/{total})")

        return results_dict

    async def _run_agent_with_browser(self, agent) -> AgentResult:
        """각 에이전트를 자체 브라우저로 실행 (격리)"""
        from crawler.agents.linemanga_app_agent import LinemangaAppAgent

        # ADB 에이전트는 브라우저 불필요 — 더미 전달
        if isinstance(agent, LinemangaAppAgent):
            return await agent.execute(None)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                return await agent.execute(browser)
            finally:
                await browser.close()


async def main():
    """Main entry point for orchestrator."""
    orchestrator = CrawlerOrchestrator()
    await orchestrator.run_all()


if __name__ == "__main__":
    asyncio.run(main())
