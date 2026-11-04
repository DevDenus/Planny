import asyncio
import logging
import signal

from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import get_engine, get_sessionmaker
from app.core.logging import configure_logging

logger = logging.getLogger("planny.worker")

TICK_SECONDS = 30


async def tick() -> None:
    """Reminders, due dates and cleanup join here at stage 5."""
    async with get_sessionmaker()() as db:
        await db.execute(text("SELECT 1"))


async def run() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)

    logger.info("worker started")
    while not stop.is_set():
        try:
            await tick()
        except Exception:
            # One bad tick must not stop the worker: the next one retries.
            logger.exception("worker tick failed")
        try:
            await asyncio.wait_for(stop.wait(), TICK_SECONDS)
        except TimeoutError:
            continue
    await get_engine().dispose()
    logger.info("worker stopped")


def main() -> None:
    configure_logging(get_settings().log_level)
    asyncio.run(run())


if __name__ == "__main__":
    main()
