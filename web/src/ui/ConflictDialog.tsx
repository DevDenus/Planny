import { Button } from "./Button";
import { Dialog } from "./Dialog";

export type ConflictDialogProps = {
  /** "Саша, сегодня, 17:00". Left out when the server doesn't know who changed the object. */
  lastChange?: string;
  saving?: boolean;
  onShowNew: () => void;
  onOverwrite: () => void;
  onClose: () => void;
};

export function ConflictDialog({
  lastChange,
  saving,
  onShowNew,
  onOverwrite,
  onClose,
}: ConflictDialogProps) {
  return (
    <Dialog
      title="Объект изменился, пока вы его редактировали"
      width={460}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onShowNew} disabled={saving}>
            Показать новую версию
          </Button>
          <Button onClick={onOverwrite} loading={saving}>
            Сохранить мои изменения
          </Button>
        </>
      }
    >
      {lastChange ? <p>Последнее изменение: {lastChange}</p> : null}
    </Dialog>
  );
}
