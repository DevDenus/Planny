import { useState, type FormEvent } from "react";

import type { TaskSummary } from "../../../api/client";
import { Banner, Button, Dialog, SelectField } from "../../../ui";
import { useMoveCard, useTaskList } from "../../tasks/api";
import { useBoards, useColumns } from "../api";

const START = "start";
const END = "end";

export type MoveCardDialogProps = {
  task: TaskSummary;
  onClose: () => void;
};

/** The way to move a card without dragging it, and the main one on a phone. */
export function MoveCardDialog({ task, onClose }: MoveCardDialogProps) {
  const { data: boards } = useBoards();
  const [boardId, setBoardId] = useState(task.board_id);
  const [chosenColumn, setChosenColumn] = useState(task.column_id);
  const [place, setPlace] = useState(END);
  const { data: columns } = useColumns(boardId);
  const moveCard = useMoveCard();

  const column =
    columns?.find((item) => item.id === chosenColumn) ?? columns?.find((item) => !item.is_done);
  const { data: cards } = useTaskList(
    { column_id: column?.id, status: "all", sort: "position", limit: 100 },
    column !== undefined,
  );
  const others = (cards?.pages.flatMap((page) => page.items) ?? []).filter(
    (item) => item.id !== task.id,
  );
  const writable = (boards ?? []).filter(
    (board) => board.my_role !== "viewer" && board.archived_at === null,
  );
  const leavesBoard = boardId !== task.board_id;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!column) return;
    // An absent after_id is the end of the column, so a card in a long column still lands last.
    const afterId = place === START ? null : place === END ? undefined : place;
    moveCard.mutate({ task, columnId: column.id, columnIsDone: column.is_done, afterId });
    onClose();
  };

  return (
    <Dialog
      title="Переместить в…"
      width={440}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Отмена
          </Button>
          <Button type="submit" form="move-card-form" disabled={!column}>
            Переместить
          </Button>
        </>
      }
    >
      <form id="move-card-form" onSubmit={submit} noValidate>
        <SelectField
          label="Доска"
          value={boardId}
          options={writable.map((board) => ({ value: board.id, label: board.name }))}
          onChange={(event) => {
            setBoardId(event.target.value);
            setChosenColumn("");
            setPlace(END);
          }}
        />
        <SelectField
          label="Колонка"
          value={column?.id ?? ""}
          options={(columns ?? []).map((item) => ({ value: item.id, label: item.name }))}
          onChange={(event) => {
            setChosenColumn(event.target.value);
            setPlace(END);
          }}
        />
        <SelectField
          label="Место"
          value={place}
          options={[
            { value: START, label: "В начало" },
            { value: END, label: "В конец" },
            ...others.map((item) => ({ value: item.id, label: `После: ${item.title}` })),
          ]}
          onChange={(event) => setPlace(event.target.value)}
        />
      </form>
      {leavesBoard && (
        <Banner tone="warning">
          Метки сбросятся, а исполнители, которых нет на новой доске, будут сняты.
        </Banner>
      )}
    </Dialog>
  );
}
