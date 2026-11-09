import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props { children: ReactNode; onReset?: () => void }
interface State { error: Error | null }

// Catches render-time errors so one broken panel shows a message instead of a blank page.
// The message is rendered as text. The component stack goes to the console for developers, not to the screen.
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("UI render error:", error, info.componentStack);
  }

  private reset = () => {
    this.setState({ error: null });
    this.props.onReset?.();
  };

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="state failed" role="alert">
        <strong>This page hit an unexpected error.</strong> {this.state.error.message}
        <div style={{ marginTop: 8 }}>
          <button onClick={this.reset}>Try again</button>{" "}
          <button className="link" onClick={() => window.location.reload()}>Reload (you will need to sign in again)</button>
        </div>
      </div>
    );
  }
}
