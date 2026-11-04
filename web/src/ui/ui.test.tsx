import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { Avatar, Banner, Button, IconButton, PasswordField, TextField } from "./index";
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
