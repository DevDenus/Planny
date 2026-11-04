import { useQueryClient } from "@tanstack/react-query";
import { Archive, ArchiveRestore, LogOut, Trash2, UserPlus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router";

import { ApiError, type Board, type BoardRole } from "../../api/client";
import { BOARDS_KEY } from "../../api/queryClient";
import {
  Avatar,
  Banner,
  Button,
  ConflictDialog,
  Dialog,
  IconButton,
  SegmentedControl,
  SelectField,
  TextArea,
  TextField,
  cx,
} from "../../ui";
import { useCurrentUser } from "../auth/session";
import { ROLE_LABELS } from "../tasks/labels";
import {
  useAddMember,
  useBoard,
  useCreateBoard,
  useMembers,
  useRemoveMember,
  useUpdateBoard,
  useUpdateMember,
  useUsers,
} from "./api";
import { BOARD_ICONS } from "./BoardIcon";
import styles from "./BoardDialog.module.css";
import { BoardLabels } from "./BoardLabels";

const ROLE_OPTIONS = (Object.keys(ROLE_LABELS) as BoardRole[]).map((value) => ({
  value,
  label: ROLE_LABELS[value],
}));
const NAME_MAX_LENGTH = 100;

function errorText(error: unknown): string | undefined {
  if (!error) return undefined;
  return error instanceof ApiError ? error.message : "Не удалось сохранить. Попробуйте ещё раз";
}

function Members({ board }: { board: Board }) {
  const navigate = useNavigate();
  const { data: me } = useCurrentUser();
  const { data: members } = useMembers(board.id);
  const isOwner = board.my_role === "owner" && board.archived_at === null;
  const { data: users } = useUsers(isOwner);
  const add = useAddMember(board.id);
  const update = useUpdateMember(board.id);
  const remove = useRemoveMember(board.id);
  const [newUser, setNewUser] = useState("");
  const [newRole, setNewRole] = useState<BoardRole>("editor");

  const candidates = (users ?? []).filter(
    (user) => !members?.some((member) => member.user.id === user.id),
  );
  const failure = add.error ?? update.error ?? remove.error;

  return (
    <section className={styles.members}>
      <h3 className={styles.heading}>Участники</h3>
      {failure ? <Banner tone="error">{errorText(failure)}</Banner> : null}
      <ul className={styles.memberList}>
        {members?.map((member) => (
          <li key={member.user.id} className={styles.member}>
            <Avatar name={member.user.display_name} color={member.user.color} />
            <span className={styles.memberName}>{member.user.display_name}</span>
            {isOwner ? (
              <SelectField
                hideLabel
                label={`Роль: ${member.user.display_name}`}
                className={styles.role}
                value={member.role}
                options={ROLE_OPTIONS}
                onChange={(event) =>
                  update.mutate({
                    userId: member.user.id,
                    role: event.target.value as BoardRole,
                  })
                }
              />
            ) : (
              <span className={styles.roleText}>{ROLE_LABELS[member.role]}</span>
            )}
            {isOwner &&
              (member.user.id === me?.id ? (
                <span className={styles.noAction} />
              ) : (
                <IconButton
                  label={`Убрать: ${member.user.display_name}`}
                  onClick={() => remove.mutate(member.user.id)}
                >
                  <Trash2 size={18} />
                </IconButton>
              ))}
          </li>
        ))}
      </ul>

      {isOwner && candidates.length > 0 && (
        <div className={styles.add}>
          <SelectField
            hideLabel
            label="Кого добавить"
            value={newUser}
            options={[
              { value: "", label: "Выберите человека" },
              ...candidates.map((user) => ({ value: user.id, label: user.display_name })),
            ]}
            onChange={(event) => setNewUser(event.target.value)}
          />
          <SelectField
            hideLabel
            label="Роль нового участника"
            value={newRole}
            options={ROLE_OPTIONS}
            onChange={(event) => setNewRole(event.target.value as BoardRole)}
          />
          <Button
            variant="secondary"
            icon={<UserPlus size={18} />}
            disabled={!newUser}
            loading={add.isPending}
            onClick={() =>
              add.mutate({ user_id: newUser, role: newRole }, { onSuccess: () => setNewUser("") })
            }
          >
            Добавить
          </Button>
        </div>
      )}

      {/* A personal board stays with its creator, who comes first in the member list. */}
      {me && !(board.is_default && members?.[0]?.user.id === me.id) && (
        <Button
          variant="ghost"
          icon={<LogOut size={18} />}
          loading={remove.isPending}
          onClick={() =>
            remove.mutate(me.id, { onSuccess: () => void navigate("/boards", { replace: true }) })
          }
        >
          Выйти с доски
        </Button>
      )}
    </section>
  );
}

export type BoardDialogProps = {
  /** Without a board the dialog creates one. */
  board?: Board;
  onClose: () => void;
};

export function BoardDialog({ board: fromPage, onClose }: BoardDialogProps) {
  const client = useQueryClient();
  // Read here and not from the prop: the rebuild below has to see the data it waited for, and
  // the page that owns the prop hasn't rendered it yet at that moment.
  const { data: fresh } = useBoard(fromPage?.id);
  const board = fresh ?? fromPage;
  // Bumped by "show the new version": the form rebuilds its starting state from fresh data.
  const [revision, setRevision] = useState(0);

  return (
    <BoardForm
      key={revision}
      board={board}
      onClose={onClose}
      onShowNew={() => {
        void client.invalidateQueries({ queryKey: BOARDS_KEY }).then(() => {
          setRevision((current) => current + 1);
        });
      }}
    />
  );
}

type BoardView = Board["default_view"];
type BoardFields = { name: string; description: string; icon: string; view: BoardView };

const VIEW_OPTIONS: { value: BoardView; label: string }[] = [
  { value: "list", label: "Список" },
  { value: "kanban", label: "Kanban" },
];

/** Only the fields the user changed, so an edit doesn't send back what someone else changed. */
function changes(base: BoardFields, draft: BoardFields) {
  const name = draft.name.trim();
  const description = draft.description.trim() || null;
  return {
    ...(name !== base.name.trim() && { name }),
    ...(description !== (base.description.trim() || null) && { description }),
    ...(draft.icon !== base.icon && { icon: draft.icon }),
    ...(draft.view !== base.view && { default_view: draft.view }),
  };
}

type BoardFormProps = BoardDialogProps & { onShowNew: () => void };

function BoardForm({ board, onClose, onShowNew }: BoardFormProps) {
  const navigate = useNavigate();
  const create = useCreateBoard();
  const update = useUpdateBoard();
  // The state the user started from. The board keeps refreshing underneath the open form, and
  // comparing with that would send someone else's change back as an edit of this user.
  const [base] = useState<BoardFields>(() => ({
    name: board?.name ?? "",
    description: board?.description ?? "",
    icon: board?.icon ?? BOARD_ICONS[0]?.key ?? "list-checks",
    view: board?.default_view ?? "list",
  }));
  const [version] = useState(board?.version ?? 1);
  // One id for the life of the form, so a retry after a lost response can't create a second board.
  const [newId] = useState(() => crypto.randomUUID());
  const [name, setName] = useState(base.name);
  const [description, setDescription] = useState(base.description);
  const [icon, setIcon] = useState(base.icon);
  const [view, setView] = useState(base.view);
  const [nameError, setNameError] = useState<string>();
  const [conflict, setConflict] = useState<{ version: number } | null>(null);

  const canEdit = !board || (board.my_role === "owner" && board.archived_at === null);
  const canArchive = board?.my_role === "owner" && !board.is_default;
  const failure = create.error ?? (conflict ? null : update.error);

  const save = (expected: number) => {
    if (!board) return;
    const body = changes(base, { name, description, icon, view });
    if (Object.keys(body).length === 0) {
      onClose();
      return;
    }
    update.mutate(
      { id: board.id, body: { ...body, version: expected } },
      {
        onSuccess: onClose,
        onError: (error) => {
          if (error instanceof ApiError && error.code === "version_conflict") {
            const current = error.details.current as Board;
            setConflict({ version: current.version });
          }
        },
      },
    );
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim()) {
      setNameError("Введите название");
      return;
    }
    setNameError(undefined);
    if (board) {
      save(version);
      return;
    }
    create.mutate(
      {
        id: newId,
        name: name.trim(),
        description: description.trim() || null,
        icon,
        default_view: view,
      },
      { onSuccess: (created) => void navigate(`/boards/${created.id}`) },
    );
  };

  const setArchived = (archived: boolean) => {
    if (board) {
      update.mutate(
        { id: board.id, body: { version: board.version, archived } },
        {
          onSuccess: onClose,
        },
      );
    }
  };

  return (
    <Dialog
      title={board ? "Настройки доски" : "Новая доска"}
      onClose={onClose}
      footer={
        canEdit ? (
          <>
            <Button variant="secondary" onClick={onClose}>
              Отмена
            </Button>
            <Button type="submit" form="board-form" loading={create.isPending || update.isPending}>
              Сохранить
            </Button>
          </>
        ) : undefined
      }
    >
      <form id="board-form" className={styles.form} onSubmit={submit} noValidate>
        {failure ? <Banner tone="error">{errorText(failure)}</Banner> : null}
        <TextField
          label="Название"
          value={name}
          maxLength={NAME_MAX_LENGTH}
          error={nameError}
          disabled={!canEdit}
          onChange={(event) => setName(event.target.value)}
        />
        <fieldset className={styles.icons} disabled={!canEdit}>
          <legend className={styles.legend}>Иконка</legend>
          <div className={styles.iconRow}>
            {BOARD_ICONS.map(({ key, label, Icon }) => (
              <label
                key={key}
                title={label}
                className={cx(styles.iconOption, icon === key && styles.iconSelected)}
              >
                <input
                  type="radio"
                  name="board-icon"
                  className={styles.iconInput}
                  aria-label={label}
                  checked={icon === key}
                  onChange={() => setIcon(key)}
                />
                <Icon size={20} aria-hidden="true" />
              </label>
            ))}
          </div>
        </fieldset>
        <TextArea
          label="Описание"
          value={description}
          disabled={!canEdit}
          onChange={(event) => setDescription(event.target.value)}
        />
        {canEdit && (
          <div className={styles.view}>
            <span className={styles.legend}>Вид по умолчанию</span>
            <SegmentedControl
              label="Вид по умолчанию"
              value={view}
              options={VIEW_OPTIONS}
              onChange={setView}
            />
          </div>
        )}
      </form>

      {board && <Members board={board} />}
      {board && (
        <BoardLabels
          boardId={board.id}
          canEdit={board.my_role !== "viewer" && board.archived_at === null}
        />
      )}

      {canArchive && (
        <Button
          variant="danger"
          icon={board.archived_at ? <ArchiveRestore size={18} /> : <Archive size={18} />}
          loading={update.isPending}
          onClick={() => setArchived(board.archived_at === null)}
        >
          {board.archived_at ? "Вернуть из архива" : "Архивировать доску"}
        </Button>
      )}

      {conflict && (
        <ConflictDialog
          saving={update.isPending}
          onClose={() => setConflict(null)}
          onShowNew={onShowNew}
          onOverwrite={() => {
            const expected = conflict.version;
            setConflict(null);
            save(expected);
          }}
        />
      )}
    </Dialog>
  );
}
