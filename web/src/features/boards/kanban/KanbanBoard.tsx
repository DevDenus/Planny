import { Plus } from "lucide-react";
import { Fragment, useRef, useState, type UIEvent } from "react";

import type { Board, BoardColumn, TaskFilters } from "../../../api/client";
import { Button, cx } from "../../../ui";
import { useDragLayer } from "../dnd/dragContext";
import { DragLayer } from "../dnd/DragLayer";
import { NewColumnDialog } from "./ColumnDialogs";
import styles from "./Kanban.module.css";
import { CardPreview } from "./KanbanCard";
import { KanbanColumn } from "./KanbanColumn";

function ColumnDropLine() {
  return <div className={styles.columnLine} data-drop-line aria-hidden="true" />;
}

type RowProps = {
  board: Board;
  columns: BoardColumn[];
  filters: TaskFilters;
  now: Date;
  timeZone: string;
};

function KanbanRow({ board, columns, filters, now, timeZone }: RowProps) {
  const { drag, readOnly } = useDragLayer();
  const [adding, setAdding] = useState(false);
  const [current, setCurrent] = useState(0);
  const row = useRef<HTMLDivElement>(null);
  const columnLine = drag?.kind === "column" ? drag.afterId : undefined;

  const trackColumn = (event: UIEvent<HTMLDivElement>) => {
    const { scrollLeft } = event.currentTarget;
    const first = event.currentTarget.querySelector("section");
    if (first) setCurrent(Math.round(scrollLeft / (first.offsetWidth || 1)));
  };

  return (
    <div className={styles.board}>
      <div ref={row} className={styles.row} onScroll={trackColumn}>
        {columnLine === null && <ColumnDropLine />}
        {columns.map((column) => (
          <Fragment key={column.id}>
            <KanbanColumn
              board={board}
              column={column}
              columns={columns}
              filters={filters}
              now={now}
              timeZone={timeZone}
            />
            {columnLine === column.id && <ColumnDropLine />}
          </Fragment>
        ))}
        {!readOnly && (
          <div className={styles.addColumn}>
            <Button variant="secondary" icon={<Plus size={18} />} onClick={() => setAdding(true)}>
              Колонка
            </Button>
          </div>
        )}
      </div>
      <div className={styles.dots} aria-hidden="true">
        {columns.map((column, index) => (
          <span key={column.id} className={cx(styles.dot, index === current && styles.dotOn)} />
        ))}
      </div>
      {adding && <NewColumnDialog boardId={board.id} onClose={() => setAdding(false)} />}
    </div>
  );
}

export type KanbanBoardProps = RowProps & { readOnly: boolean };

export function KanbanBoard({ readOnly, ...props }: KanbanBoardProps) {
  const { board, columns, now, timeZone } = props;
  return (
    <DragLayer
      boardId={board.id}
      columns={columns}
      stacked={false}
      readOnly={readOnly}
      preview={(drag) =>
        drag.kind === "card" ? (
          <CardPreview task={drag.task} now={now} timeZone={timeZone} />
        ) : (
          <div className={cx(styles.column, styles.columnPreview)}>
            <div className={styles.columnHeader}>
              <h2 className={styles.columnTitle}>{drag.column.name}</h2>
            </div>
          </div>
        )
      }
    >
      <KanbanRow {...props} />
    </DragLayer>
  );
}
