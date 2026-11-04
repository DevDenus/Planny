"""Board creation without access checks. It imports nothing from identity: identity calls it
while creating a user, and the other direction would be an import cycle."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id
from app.core.ordering import key_between
from app.tasks.models import Board, BoardColumn, BoardMember, BoardRole, BoardView

PERSONAL_BOARD_NAME = "Личная доска"
PERSONAL_BOARD_ICON = "inbox"
DEFAULT_COLUMNS = (("К выполнению", False), ("Готово", True))


async def add_board(
    db: AsyncSession,
    *,
    owner_id: UUID,
    name: str,
    icon: str,
    board_id: UUID | None = None,
    description: str | None = None,
    default_view: BoardView = BoardView.list,
    is_default: bool = False,
) -> Board:
    board = Board(
        id=board_id or new_id(),
        name=name,
        description=description,
        icon=icon,
        default_view=default_view,
        is_default=is_default,
        created_by=owner_id,
    )
    db.add(board)
    # The models have no relationships, so the flush order between tables is not derived.
    await db.flush()
    position = None
    for column_name, is_done in DEFAULT_COLUMNS:
        position = key_between(position, None)
        db.add(BoardColumn(board_id=board.id, name=column_name, position=position, is_done=is_done))
    db.add(BoardMember(board_id=board.id, user_id=owner_id, role=BoardRole.owner))
    await db.flush()
    return board


async def add_personal_board(db: AsyncSession, user_id: UUID) -> Board:
    return await add_board(
        db,
        owner_id=user_id,
        name=PERSONAL_BOARD_NAME,
        icon=PERSONAL_BOARD_ICON,
        is_default=True,
    )
