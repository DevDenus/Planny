from datetime import timedelta

from sqlalchemy import select

from app import worker
from app.core.clock import utcnow
from app.core.db import get_sessionmaker
from app.identity.models import UserSession
from app.notifications.models import Notification, NotificationKind
from app.reminders import jobs
from tests.conftest import make_user


async def test_expired_session_goes_and_live_one_stays() -> None:
    user = await make_user("sasha")
    now = utcnow()
    async with get_sessionmaker()() as db:
        db.add_all(
            [
                UserSession(
                    user_id=user.id,
                    token_hash="expired",
                    last_seen_at=now - timedelta(days=31),
                    expires_at=now - timedelta(minutes=1),
                ),
                UserSession(
                    user_id=user.id,
                    token_hash="live",
                    last_seen_at=now,
                    expires_at=now + timedelta(days=30),
                ),
            ]
        )
        await db.commit()

    await jobs.clean_up(get_sessionmaker(), now)

    async with get_sessionmaker()() as db:
        kept = set(await db.scalars(select(UserSession.token_hash)))
    assert kept == {"live"}


async def test_only_notifications_read_over_90_days_ago_go() -> None:
    user = await make_user("sasha")
    now = utcnow()
    async with get_sessionmaker()() as db:
        db.add_all(
            [
                Notification(
                    user_id=user.id,
                    kind=NotificationKind.board_added,
                    title="Прочитано давно",
                    created_at=now - timedelta(days=120),
                    read_at=now - timedelta(days=91),
                ),
                Notification(
                    user_id=user.id,
                    kind=NotificationKind.board_added,
                    title="Прочитано недавно",
                    created_at=now - timedelta(days=120),
                    read_at=now - timedelta(days=89),
                ),
                Notification(
                    user_id=user.id,
                    kind=NotificationKind.board_added,
                    title="Не прочитано",
                    created_at=now - timedelta(days=400),
                ),
            ]
        )
        await db.commit()

    await jobs.clean_up(get_sessionmaker(), now)

    async with get_sessionmaker()() as db:
        kept = set(await db.scalars(select(Notification.title)))
    assert kept == {"Прочитано недавно", "Не прочитано"}


async def test_tick_runs_on_an_empty_database() -> None:
    await worker.tick()
