import { render, screen } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { routes } from "./routes";

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<RouterProvider router={router} />);
  return router;
}

describe("app shell routes", () => {
  it("renders the sidebar and dashboard at /", () => {
    renderAt("/");
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(nav).toHaveTextContent("Dashboard");
    expect(nav).toHaveTextContent("Upload lecture");
    expect(nav).toHaveTextContent("Analytics");
    expect(nav).toHaveTextContent("LLMOps");
    expect(screen.getByRole("heading", { level: 1, name: "Dashboard" })).toBeInTheDocument();
  });

  it("redirects a lecture to its transcript tab and shows all six tabs", async () => {
    const router = renderAt("/lectures/abc");
    expect(await screen.findByRole("heading", { level: 1, name: "Transcript" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/lectures/abc/transcript");
    const tabs = screen.getByRole("navigation", { name: "Lecture tabs" });
    for (const label of ["Transcript", "Summary & Notes", "Quiz", "Ask", "Flashcards", "Mind Map"]) {
      expect(tabs).toHaveTextContent(label);
    }
  });

  it("renders auth pages outside the shell", () => {
    renderAt("/login");
    expect(screen.getByRole("heading", { level: 1, name: "Log in" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Main" })).not.toBeInTheDocument();
  });

  it("shows a 404 for unknown routes", () => {
    renderAt("/nope");
    expect(screen.getByText("Page not found")).toBeInTheDocument();
  });
});
