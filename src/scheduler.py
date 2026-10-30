"""
scheduler.py - Scheduler zilnic cu reincercari pentru preturile OPCOM

Daca preturile nu sunt inca publicate la ora de rulare,
reintercearca la intervalul configurat.
"""

import asyncio
import logging
import signal
import sys
import time
from datetime import datetime
from typing import Callable, Awaitable

import schedule
import pytz

logger = logging.getLogger(__name__)


class ArbitrageScheduler:
    def __init__(
        self,
        run_time: str = "12:00",
        timezone: str = "Europe/Bucharest",
        run_on_start: bool = False,
        retry_count: int = 5,
        retry_wait_minutes: int = 15,
    ):
        self.run_time = run_time
        self.timezone = pytz.timezone(timezone)
        self.run_on_start = run_on_start
        self.retry_count = retry_count
        self.retry_wait_minutes = retry_wait_minutes
        self._running = False
        self._job_func: Callable[[], Awaitable[bool]] = None

    def set_job(self, func: Callable[[], Awaitable[bool]]) -> None:
        self._job_func = func

    def start(self) -> None:
        if not self._job_func:
            raise ValueError("Seteaza job-ul cu set_job() inainte de start()")

        self._running = True
        self._setup_signals()

        schedule.every().day.at(self.run_time).do(
            lambda: asyncio.run(self._run_with_retry())
        )

        logger.info(
            f"Scheduler activ. Executie zilnica la {self.run_time} "
            f"(max {self.retry_count} reincercari la {self.retry_wait_minutes}min interval)"
        )

        if self.run_on_start:
            logger.info("run_on_start=True: Prima rulare imediata...")
            asyncio.run(self._run_with_retry())

        self._log_next_run()

        while self._running:
            schedule.run_pending()
            time.sleep(30)

    async def _run_with_retry(self) -> None:
        """Incearca sa ruleze botul, cu reincercari daca preturile nu sunt disponibile."""
        for attempt in range(1, self.retry_count + 1):
            logger.info(
                f"\n{'='*55}\n"
                f"EXECUTIE {datetime.now().strftime('%d.%m.%Y %H:%M:%S')} "
                f"(incercare {attempt}/{self.retry_count})\n"
                f"{'='*55}"
            )
            try:
                success = await self._job_func()
                if success:
                    logger.info(f"✅ Executie reusita la incercarea {attempt}")
                    break
                else:
                    if attempt < self.retry_count:
                        logger.warning(
                            f"Executie esuata. Reincercare in {self.retry_wait_minutes} minute..."
                        )
                        await asyncio.sleep(self.retry_wait_minutes * 60)
            except Exception as e:
                logger.error(f"Eroare: {e}", exc_info=True)
                if attempt < self.retry_count:
                    await asyncio.sleep(self.retry_wait_minutes * 60)

        self._log_next_run()

    def _log_next_run(self) -> None:
        next_run = schedule.next_run()
        if next_run:
            delta = next_run - datetime.now()
            h = int(delta.total_seconds() // 3600)
            m = int((delta.total_seconds() % 3600) // 60)
            logger.info(f"Urmatoarea executie: {next_run.strftime('%d.%m.%Y %H:%M')} (in {h}h {m}min)")

    def _setup_signals(self) -> None:
        def shutdown(signum, frame):
            logger.info("Oprire scheduler...")
            self._running = False
            schedule.clear()
            sys.exit(0)
        signal.signal(signal.SIGINT, shutdown)
        signal.signal(signal.SIGTERM, shutdown)
