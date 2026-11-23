import { Component, type ReactNode } from "react";

/** A part of the page that shows `fallback` instead when it fails to draw, so one memory can't blank the console. */
export class Guarded extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  override state = { failed: false };

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true };
  }

  override render(): ReactNode {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}
