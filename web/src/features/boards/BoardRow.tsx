import type { TaskSummary } from "../../api/client";
import { TaskRow, type TaskRowProps } from "../tasks/TaskRow";
import { useCardHandle } from "./dnd/useDragHandles";
import styles from "./BoardColumnSection.module.css";

/** The copy of a row under the pointer. */
export function BoardRowPreview({ task }: { task: TaskSummary }) {
  return <div className={styles.preview}>{task.title}</div>;
}

/** A row of the list view of a board, which can be dragged like a Kanban card. */
export function BoardRow(props: Omit<TaskRowProps, "drag">) {
  const handle = useCardHandle(props.task);
  return <TaskRow {...props} drag={handle} />;
}
