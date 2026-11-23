import { describe, expect, it, vi } from "vitest";

import { Guarded } from "./Guarded";

/** A boundary as React holds it, its state set at once rather than on the next render. */
function boundary(resetKey: unknown) {
  const guarded = new Guarded({ fallback: "fallback", children: "children", resetKey });
  guarded.setState = (state) => Object.assign(guarded.state, state);
  return guarded;
}

describe("a part of the page that fails to draw", () => {
  it("shows its fallback once a child has thrown", () => {
    const guarded = boundary("first");
    Object.assign(guarded.state, Guarded.getDerivedStateFromError());

    expect(guarded.render()).toBe("fallback");
  });

  it("tries its children again when its reset key changes, and not before", () => {
    const guarded = boundary("first");
    Object.assign(guarded.state, Guarded.getDerivedStateFromError());

    guarded.componentDidUpdate({ resetKey: "first" });
    expect(guarded.render()).toBe("fallback");

    Object.assign(guarded, { props: { ...guarded.props, resetKey: "second" } });
    guarded.componentDidUpdate({ resetKey: "first" });
    expect(guarded.render()).toBe("children");
  });

  it("says what failed", () => {
    const said = vi.spyOn(console, "error").mockImplementation(() => {});

    boundary("first").componentDidCatch(new Error("too deep"), { componentStack: "" });

    expect(said).toHaveBeenCalledWith("A part of the page couldn't be drawn", new Error("too deep"), "");
    said.mockRestore();
  });
});
