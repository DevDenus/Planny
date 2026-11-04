import asyncio
import getpass
import os
from collections.abc import Awaitable, Callable
from typing import Annotated

import typer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_engine, get_sessionmaker
from app.core.errors import AppError
from app.core.principal import Operator
from app.identity import service

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Команды оператора Planny.")
users_app = typer.Typer(no_args_is_help=True, help="Управление пользователями.")
app.add_typer(users_app, name="users")


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
    """Заблокировать пользователя и закрыть его сессии."""
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


def main() -> None:
    app()
