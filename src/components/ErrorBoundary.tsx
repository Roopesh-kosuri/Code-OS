import React, { Component, ErrorInfo, ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("[ErrorBoundary] Uncaught exception:", error, errorInfo);
  }

  private handleReset = () => {
    this.setState({ hasError: false, error: null });
  };

  public render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: 24, textAlign: "center", fontFamily: "system-ui, sans-serif" }}>
          <h2>Something went wrong</h2>
          <p style={{ opacity: 0.8, fontSize: 14 }}>
            {this.state.error?.message || "An unexpected error occurred."}
          </p>
          <button
            onClick={this.handleReset}
            style={{
              padding: "8px 16px",
              marginTop: 12,
              cursor: "pointer",
              borderRadius: 4,
              border: "1px solid #ccc",
              background: "#333",
              color: "#fff",
            }}
          >
            Try Again
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
