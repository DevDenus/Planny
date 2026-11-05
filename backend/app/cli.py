import asyncio
import getpass
import os
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Annotated
from uuid import UUID

import typer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.db import get_engine, get_sessionmaker
from app.core.errors import AppError
from app.core.principal import Operator
from app.identity import key_service, service

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Команды оператора Planny.")
users_app = typer.Typer(no_args_is_help=True, help="Управление пользователями.")
app.add_typer(users_app, name="users")
keys_app = typer.Typer(no_args_is_help=True, help="Управление ключами интеграций.")
app.add_typer(keys_app, name="keys")


def _operator() -> Operator:
    return Operator(actor=os.environ.get("PLANNY_ACTOR") or getpass.getuser())


def _run[T](command: Callable[[Operator, AsyncSession], Awaitable[T]]) -> T:
    async def run() -> T:
        try:
            async with get_sessionmaker()() as db:
                return await command(_operator(), db)
        finally:
            await get_engine().dispose()

    try:
        return asyncio.run(run())
    except AppError as error:
        fields = error.details.get("fields", {})
        typer.echo("; ".join(fields.values()) or error.message, err=True)
        raise typer.Exit(1) from None


@users_app.command("create")
def users_create(
    login: str,
    name: Annotated[str, typer.Option("--name", help="Отображаемое имя.")],
) -> None:
    """Создать пользователя и вывести одноразовый пароль."""
    user, password = _run(
        lambda operator, db: service.create_user(operator, db, login=login, display_name=name)
    )
    typer.echo(f"Пользователь {user.login} создан.")
    typer.echo(f"Одноразовый пароль: {password}")


@users_app.command("list")
def users_list() -> None:
    """Список пользователей."""
    users = _run(service.list_users)
    for user in users:
        typer.echo(f"{user.login}\t{user.display_name}\t{user.status.value}")


@users_app.command("block")
def users_block(login: str) -> None:
    """Заблокировать пользователя, закрыть его сессии и отозвать ключи."""
    _run(lambda operator, db: service.block_user(operator, db, login))
    typer.echo(f"Пользователь {login} заблокирован.")


@users_app.command("unblock")
def users_unblock(login: str) -> None:
    """Разблокировать пользователя."""
    _run(lambda operator, db: service.unblock_user(operator, db, login))
    typer.echo(f"Пользователь {login} разблокирован.")


@users_app.command("reset-password")
def users_reset_password(login: str) -> None:
    """Выдать новый одноразовый пароль и закрыть сессии пользователя."""
    password = _run(lambda operator, db: service.reset_password(operator, db, login))
    typer.echo(f"Одноразовый пароль: {password}")


@keys_app.command("create")
def keys_create(
    user: Annotated[str, typer.Option("--user", help="Логин владельца ключа.")],
    name: Annotated[str, typer.Option("--name", help="Название ключа, например интеграции.")],
    scopes: Annotated[
        str, typer.Option("--scopes", help="Права через запятую, например events:read,tasks:read.")
    ],
    expires: Annotated[
        datetime | None,
        typer.Option(
            "--expires",
            formats=["%Y-%m-%d"],
            help="Последний день действия (ГГГГ-ММ-ДД) по часовому поясу владельца.",
        ),
    ] = None,
) -> None:
    """Выпустить ключ интеграции и вывести его секрет."""
    key, secret = _run(
        lambda operator, db: key_service.create_key(
            operator,
            db,
            login=user,
            name=name,
            scopes=scopes.split(","),
            expires=expires.date() if expires is not None else None,
        )
    )
    typer.echo(f"Ключ {key.name} для {user} создан.")
    typer.echo(f"Секрет (показывается один раз): {secret}")


@keys_app.command("list")
def keys_list(
    user: Annotated[
        str | None, typer.Option("--user", help="Показать ключи только этого пользователя.")
    ] = None,
) -> None:
    """Список ключей и их состояние. Секреты и хеши не показываются."""
    rows = _run(lambda operator, db: key_service.list_keys(operator, db, login=user))
    now = utcnow()
    for key, login in rows:
        columns = [
            str(key.id),
            login,
            key.name,
            f"pln_{key.prefix}",
            ",".join(key.scopes),
            key_service.key_state(key, now),
            key.expires_at.isoformat() if key.expires_at else "-",
            key.last_used_at.isoformat() if key.last_used_at else "-",
        ]
        typer.echo("\t".join(columns))


@keys_app.command("revoke")
def keys_revoke(key_id: UUID) -> None:
    """Отозвать ключ: он перестанет работать сразу."""
    _run(lambda operator, db: key_service.revoke_key(operator, db, key_id))
    typer.echo("Ключ отозван.")


def main() -> None:
    app()
