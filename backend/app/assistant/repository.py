from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.models import AssistantChat, AssistantMessage


async def list_chats(db: AsyncSession, user_id: UUID) -> Sequence[AssistantChat]:
    query = (
        select(AssistantChat)
        .where(AssistantChat.user_id == user_id)
        .order_by(AssistantChat.updated_at.desc(), AssistantChat.id.desc())
    )
    return (await db.scalars(query)).all()


async def get_chat(db: AsyncSession, chat_id: UUID, user_id: UUID) -> AssistantChat | None:
    return await db.scalar(
        select(AssistantChat).where(AssistantChat.id == chat_id, AssistantChat.user_id == user_id)
    )


async def lock_chat(db: AsyncSession, chat_id: UUID, user_id: UUID) -> AssistantChat | None:
    """Read again after the model answered: the chat may have been deleted meanwhile."""
    return await db.scalar(
        select(AssistantChat)
        .where(AssistantChat.id == chat_id, AssistantChat.user_id == user_id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )


async def messages_of(db: AsyncSession, chat_id: UUID) -> Sequence[AssistantMessage]:
    query = (
        select(AssistantMessage)
        .where(AssistantMessage.chat_id == chat_id)
        .order_by(AssistantMessage.created_at, AssistantMessage.id)
    )
    return (await db.scalars(query)).all()


async def user_texts(db: AsyncSession, chat_id: UUID) -> list[str]:
    query = (
        select(AssistantMessage.text)
        .where(AssistantMessage.chat_id == chat_id, AssistantMessage.role == "user")
        .order_by(AssistantMessage.created_at, AssistantMessage.id)
    )
    return list(await db.scalars(query))


async def delete_chat(db: AsyncSession, chat_id: UUID) -> None:
    await db.execute(delete(AssistantChat).where(AssistantChat.id == chat_id))
