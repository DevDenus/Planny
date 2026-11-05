import { Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";

import { ApiError, type Category, type LabelColor } from "../../api/client";
import {
  Banner,
  Button,
  Dialog,
  IconButton,
  Panel,
  SelectField,
  Skeleton,
  TextField,
} from "../../ui";
import {
  useCategories,
  useCreateCategory,
  useDeleteCategory,
  useUpdateCategory,
} from "../calendar/api";
import { LABEL_COLORS } from "../tasks/labels";
import styles from "./CategoriesSection.module.css";

const NAME_MAX_LENGTH = 50;
const SAVE_FAILED = "Не удалось сохранить категорию";

/** The first colour that no category uses yet, or the first colour when all of them are used. */
function freeColor(categories: Category[]): LabelColor {
  const used = new Set<LabelColor>(categories.map((category) => category.color));
  return (LABEL_COLORS.find((color) => !used.has(color.value)) ?? LABEL_COLORS[0]!).value;
}

type RowProps = {
  category: Category;
  onDelete: (category: Category) => void;
};

function CategoryRow({ category, onDelete }: RowProps) {
  const update = useUpdateCategory();
  const [name, setName] = useState(category.name);
  const nameError = update.error instanceof ApiError ? update.error.fields.name : undefined;
  // The chosen colour shows while it is saved, and the saved one again if the save fails.
  const pendingColor = update.isPending ? update.variables?.body.color : undefined;
  const color = pendingColor ?? category.color;

  const rename = () => {
    const next = name.trim();
    if (next === "") {
      setName(category.name);
      update.reset();
      return;
    }
    if (next !== category.name) {
      setName(next);
      update.mutate({ id: category.id, body: { name: next } });
    }
  };

  return (
    <li className={styles.row}>
      <div className={styles.fields}>
        <div className={styles.name}>
          <TextField
            label="Название категории"
            hideLabel
            icon={
              <span
                className={styles.swatch}
                style={{ background: `var(--cat-${color})` }}
                aria-hidden="true"
              />
            }
            value={name}
            maxLength={NAME_MAX_LENGTH}
            error={nameError}
            onChange={(event) => setName(event.target.value)}
            onBlur={rename}
            onKeyDown={(event) => {
              if (event.key === "Enter") event.currentTarget.blur();
            }}
          />
        </div>
        <div className={styles.colour}>
          <SelectField
            label="Цвет"
            hideLabel
            value={color}
            options={LABEL_COLORS}
            onChange={(event) =>
              update.mutate({
                id: category.id,
                body: { color: event.target.value as LabelColor },
              })
            }
          />
        </div>
        <IconButton
          label={`Удалить категорию ${category.name}`}
          className={styles.remove}
          onClick={() => onDelete(category)}
        >
          <Trash2 size={18} />
        </IconButton>
      </div>
      {update.error && !nameError && <Banner tone="error">{SAVE_FAILED}</Banner>}
    </li>
  );
}

function NewCategoryForm({ categories }: { categories: Category[] }) {
  const create = useCreateCategory();
  const [name, setName] = useState("");
  const [color, setColor] = useState<LabelColor>(() => freeColor(categories));
  const [blank, setBlank] = useState(false);
  const serverNameError = create.error instanceof ApiError ? create.error.fields.name : undefined;
  const nameError = blank ? "Введите название" : serverNameError;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const next = name.trim();
    setBlank(next === "");
    if (next === "") return;
    create.mutate({ name: next, color }, { onSuccess: () => setName("") });
  };

  return (
    <form className={styles.form} onSubmit={submit} noValidate>
      <TextField
        label="Новая категория"
        value={name}
        maxLength={NAME_MAX_LENGTH}
        error={nameError}
        onChange={(event) => {
          setName(event.target.value);
          setBlank(false);
        }}
      />
      <SelectField
        label="Цвет новой категории"
        value={color}
        options={LABEL_COLORS}
        onChange={(event) => setColor(event.target.value as LabelColor)}
      />
      {create.error && !serverNameError && <Banner tone="error">{SAVE_FAILED}</Banner>}
      <div>
        <Button type="submit" loading={create.isPending}>
          Добавить
        </Button>
      </div>
    </form>
  );
}

export function CategoriesSection() {
  const { data, isPending, isError, refetch } = useCategories();
  const remove = useDeleteCategory();
  const [deleting, setDeleting] = useState<Category | null>(null);

  return (
    <Panel className={styles.section}>
      <h2 className={styles.heading}>Категории</h2>
      {isPending && <Skeleton height={52} />}
      {isError && (
        <div className={styles.failure}>
          <Banner tone="error">Не удалось загрузить категории</Banner>
          <Button variant="secondary" onClick={() => void refetch()}>
            Повторить
          </Button>
        </div>
      )}
      {data && (
        <>
          <ul className={styles.list}>
            {data.map((category) => (
              <CategoryRow key={category.id} category={category} onDelete={setDeleting} />
            ))}
          </ul>
          <NewCategoryForm categories={data} />
        </>
      )}
      {deleting && (
        <Dialog
          title="Удалить категорию?"
          width={420}
          onClose={() => setDeleting(null)}
          footer={
            <>
              <Button variant="secondary" onClick={() => setDeleting(null)}>
                Отмена
              </Button>
              <Button
                variant="danger"
                loading={remove.isPending}
                onClick={() => remove.mutate(deleting.id, { onSuccess: () => setDeleting(null) })}
              >
                Удалить
              </Button>
            </>
          }
        >
          {remove.error && <Banner tone="error">{SAVE_FAILED}</Banner>}
          <p>События останутся, у них просто пропадёт эта категория.</p>
        </Dialog>
      )}
    </Panel>
  );
}
