import { Component, type ErrorInfo, type ReactNode } from "react";

/**
 * A part of the page that shows `fallback` instead when it fails to draw, so one memory can't blank the console. It
 * tries again when `resetKey` changes: new text, or another page.
 */
export class Guarded extends Component<
  { fallback: ReactNode; children: ReactNode; resetKey?: unknown },
  { failed: boolean }
> {
  override state = { failed: false };

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("A part of the page couldn't be drawn", error, info.componentStack);
  }

  override componentDidUpdate(previous: { resetKey?: unknown }): void {
    if (this.state.failed && previous.resetKey !== this.props.resetKey) this.setState({ failed: false });
  }

  override render(): ReactNode {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}
