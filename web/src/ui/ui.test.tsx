import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";

import {
  Avatar,
  Banner,
  Button,
  Checkbox,
  Dialog,
  IconButton,
  PasswordField,
  SegmentedControl,
  SelectField,
  Switch,
  TextField,
  ToastProvider,
  useToast,
} from "./index";
import type { BannerProps } from "./index";

describe("Button", () => {
  it("is disabled and busy while loading", () => {
    render(<Button loading>Сохранить</Button>);

    const button = screen.getByRole("button", { name: "Сохранить" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
  });

  it("defaults to type button", () => {
    render(<Button>Далее</Button>);

    expect(screen.getByRole("button", { name: "Далее" })).toHaveAttribute("type", "button");
  });
});

describe("IconButton", () => {
  it("hides the badge at zero", () => {
    render(
      <IconButton label="Уведомления" badge={0}>
        <span>+</span>
      </IconButton>,
    );

    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("shows 99 as is and caps larger counts at 99+", () => {
    const { rerender } = render(
      <IconButton label="Уведомления" badge={99}>
        <span>+</span>
      </IconButton>,
    );
    expect(screen.getByText("99")).toBeInTheDocument();

    rerender(
      <IconButton label="Уведомления" badge={100}>
        <span>+</span>
      </IconButton>,
    );
    expect(screen.getByText("99+")).toBeInTheDocument();
    expect(screen.queryByText("99")).not.toBeInTheDocument();
  });
});

describe("TextField", () => {
  it("links the error through aria-describedby and marks the input invalid", () => {
    render(<TextField label="Почта" error="Некорректный адрес" />);

    const input = screen.getByLabelText("Почта");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription("Некорректный адрес");
    expect(input).toHaveAttribute("aria-describedby", screen.getByText("Некорректный адрес").id);
  });
});

describe("TextField with a hidden label", () => {
  it("keeps the accessible name and shows the label as the placeholder", () => {
    render(<TextField label="Логин" hideLabel />);
    expect(screen.getByLabelText("Логин")).toHaveAttribute("placeholder", "Логин");
  });
});

describe("PasswordField", () => {
  it("toggles the input type and the toggle label", async () => {
    const user = userEvent.setup();
    render(<PasswordField label="Пароль" />);

    const input = screen.getByLabelText("Пароль");
    expect(input).toHaveAttribute("type", "password");

    await user.click(screen.getByRole("button", { name: "Показать пароль" }));
    expect(input).toHaveAttribute("type", "text");

    await user.click(screen.getByRole("button", { name: "Скрыть пароль" }));
    expect(input).toHaveAttribute("type", "password");
  });
});

describe("Avatar", () => {
  it("shows the uppercased first letter", () => {
    render(<Avatar name="anna" color="violet" />);

    expect(screen.getByTitle("anna").textContent).toBe("A");
  });

  it("falls back to teal for an unknown colour", () => {
    render(<Avatar name="boris" color="magenta" />);

    // CSS module class names stay readable in tests (non-scoped strategy in vite.config.ts).
    expect(screen.getByTitle("boris")).toHaveClass("teal");
  });
});

describe("Banner", () => {
  it.each<[BannerProps["tone"], string]>([
    ["info", "status"],
    ["success", "status"],
    ["warning", "status"],
    ["error", "alert"],
  ])("uses the right role for the %s tone", (tone, role) => {
    render(<Banner tone={tone}>Сообщение</Banner>);

    expect(screen.getByRole(role)).toHaveTextContent("Сообщение");
  });
});

describe("Checkbox", () => {
  it("reports the next value on click", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { rerender } = render(<Checkbox checked={false} onChange={onChange} label="Выполнено" />);

    await user.click(screen.getByRole("checkbox", { name: "Выполнено" }));
    expect(onChange).toHaveBeenLastCalledWith(true);

    rerender(<Checkbox checked onChange={onChange} label="Выполнено" />);
    await user.click(screen.getByRole("checkbox", { name: "Выполнено" }));
    expect(onChange).toHaveBeenLastCalledWith(false);
  });

  it("keeps its name when the label is hidden", () => {
    render(<Checkbox checked={false} onChange={vi.fn()} label="Выполнено" hideLabel />);

    expect(screen.getByRole("checkbox", { name: "Выполнено" })).not.toBeChecked();
  });
});

describe("SelectField", () => {
  it("links the error through aria-describedby and marks the select invalid", () => {
    render(
      <SelectField
        label="Приоритет"
        options={[{ value: "high", label: "Высокий" }]}
        error="Выберите приоритет"
      />,
    );

    const select = screen.getByLabelText("Приоритет");
    expect(select).toHaveAttribute("aria-invalid", "true");
    expect(select).toHaveAccessibleDescription("Выберите приоритет");
    expect(select).toHaveAttribute("aria-describedby", screen.getByText("Выберите приоритет").id);
  });
});

function DialogHost() {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Открыть
      </button>
      {open ? (
        <Dialog title="Фильтр задач" onClose={() => setOpen(false)}>
          <button type="button">Первая</button>
          <button type="button">Вторая</button>
        </Dialog>
      ) : null}
    </>
  );
}

describe("Dialog", () => {
  it("closes on Escape and on an overlay click, but not on a click inside", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <Dialog title="Событие" onClose={onClose}>
        <p>Описание</p>
      </Dialog>,
    );

    const dialog = screen.getByRole("dialog", { name: "Событие" });
    await user.click(screen.getByText("Описание"));
    expect(onClose).not.toHaveBeenCalled();

    await user.click(dialog.parentElement as HTMLElement);
    expect(onClose).toHaveBeenCalledTimes(1);

    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("moves focus into the panel and returns it to the opener", async () => {
    const user = userEvent.setup();
    render(<DialogHost />);

    const opener = screen.getByRole("button", { name: "Открыть" });
    await user.click(opener);
    expect(screen.getByRole("dialog", { name: "Фильтр задач" })).toHaveFocus();
    expect(document.body.style.overflow).toBe("hidden");

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
    expect(document.body.style.overflow).toBe("");
  });

  it("keeps Tab inside the panel", async () => {
    const user = userEvent.setup();
    render(<DialogHost />);

    await user.click(screen.getByRole("button", { name: "Открыть" }));
    await user.click(screen.getByRole("button", { name: "Вторая" }));

    await user.tab();
    expect(screen.getByRole("button", { name: "Закрыть" })).toHaveFocus();

    await user.tab({ shift: true });
    expect(screen.getByRole("button", { name: "Вторая" })).toHaveFocus();
  });
});

describe("SegmentedControl", () => {
  it("reports the choice and marks the selected segment", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const options = [
      { value: "all", label: "Все задачи" },
      { value: "mine", label: "Мои" },
    ];
    const { rerender } = render(
      <SegmentedControl label="Фильтр задач" value="all" options={options} onChange={onChange} />,
    );

    expect(screen.getByRole("radio", { name: "Все задачи" })).toHaveAttribute(
      "aria-checked",
      "true",
    );

    await user.click(screen.getByRole("radio", { name: "Мои" }));
    expect(onChange).toHaveBeenCalledWith("mine");

    rerender(
      <SegmentedControl label="Фильтр задач" value="mine" options={options} onChange={onChange} />,
    );
    expect(screen.getByRole("radio", { name: "Мои" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "Все задачи" })).toHaveAttribute(
      "aria-checked",
      "false",
    );
  });
});

describe("Switch", () => {
  it("reports the opposite state on click", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { rerender } = render(<Switch checked={false} onChange={onChange} label="Дом" />);

    const toggle = screen.getByRole("switch", { name: "Дом" });
    expect(toggle).toHaveAttribute("aria-checked", "false");

    await user.click(toggle);
    expect(onChange).toHaveBeenLastCalledWith(true);

    rerender(<Switch checked onChange={onChange} label="Дом" />);
    await user.click(toggle);
    expect(onChange).toHaveBeenLastCalledWith(false);
  });
});

function ShowToastButton() {
  const toast = useToast();

  return (
    <button type="button" onClick={() => toast.show("Сохранено")}>
      Показать
    </button>
  );
}

describe("Toast", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("shows a message and hides it with the dismiss button", async () => {
    const user = userEvent.setup();
    render(
      <ToastProvider>
        <ShowToastButton />
      </ToastProvider>,
    );

    await user.click(screen.getByRole("button", { name: "Показать" }));
    expect(screen.getByText("Сохранено")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Скрыть" }));
    expect(screen.queryByText("Сохранено")).not.toBeInTheDocument();
  });

  it("hides a message after five seconds", () => {
    // userEvent waits on real timers internally, so a synchronous click keeps the fake clock usable.
    vi.useFakeTimers();
    render(
      <ToastProvider>
        <ShowToastButton />
      </ToastProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Показать" }));
    act(() => {
      vi.advanceTimersByTime(4999);
    });
    expect(screen.getByText("Сохранено")).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.queryByText("Сохранено")).not.toBeInTheDocument();
  });

  it("keeps at most three messages", async () => {
    const user = userEvent.setup();
    render(
      <ToastProvider>
        <ShowToastButton />
      </ToastProvider>,
    );

    const button = screen.getByRole("button", { name: "Показать" });
    for (let count = 0; count < 4; count += 1) {
      await user.click(button);
    }

    expect(screen.getAllByText("Сохранено")).toHaveLength(3);
  });

  it("throws outside a provider", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});

    expect(() => render(<ShowToastButton />)).toThrow("useToast must be used inside ToastProvider");
  });
});
