import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Badge, Button, InlineNote } from "./primitives";

describe("primitivas de interface", () => {
  it("aciona o botão pelo teclado e pelo clique", async () => {
    const onClick = vi.fn();
    const user = userEvent.setup();
    render(<Button onClick={onClick}>Tentar de novo</Button>);

    await user.click(screen.getByRole("button", { name: "Tentar de novo" }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("expõe o texto da nota e o tom visual", () => {
    render(<InlineNote tone="warning">Dados defasados</InlineNote>);
    const note = screen.getByText("Dados defasados");
    expect(note).toBeVisible();
    expect(note).toHaveClass("border-l-warning/20");
  });

  it("mantém o texto visível no badge", () => {
    render(<Badge tone="positive">Atualizado</Badge>);
    expect(screen.getByText("Atualizado")).toBeVisible();
  });
});
