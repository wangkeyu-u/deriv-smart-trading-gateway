import { Component, ErrorInfo, ReactNode } from "react";

type ErrorBoundaryProps = {
  children: ReactNode;
  fallback?: ReactNode;
  onError?: (error: Error, info: ErrorInfo) => void;
};

type ErrorBoundaryState = {
  hasError: boolean;
  error: Error | null;
};

class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("[ErrorBoundary]", error, info);
    if (this.props.onError) {
      this.props.onError(error, info);
    }
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
  };

  render(): ReactNode {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      const error = this.state.error;
      return (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            minHeight: "100vh",
            padding: "2rem",
            background: "#080d0c",
            color: "#f1f4ed",
            fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif",
          }}
        >
          <div
            style={{
              maxWidth: 480,
              padding: "2rem",
              border: "1px solid #2b3a35",
              borderRadius: 12,
              background: "#0e1513",
              boxShadow: "0 28px 80px rgba(0,0,0,0.34)",
            }}
          >
            <div style={{ fontSize: 14, color: "#ed7b72", marginBottom: 12 }}>
              ⚠ Component Error
            </div>
            <h2 style={{ fontSize: 18, margin: "0 0 8px", fontWeight: 650 }}>
              Something went wrong
            </h2>
            <p style={{ fontSize: 13, color: "#a1aaa3", margin: "0 0 16px" }}>
              The UI encountered an unexpected error. You can try reloading the
              module or refreshing the page.
            </p>
            {error && (
              <pre
                style={{
                  fontSize: 11,
                  color: "#67746e",
                  background: "#07110f",
                  padding: 12,
                  borderRadius: 8,
                  overflow: "auto",
                  maxHeight: 160,
                  margin: "0 0 16px",
                  fontFamily: "SFMono-Regular, Consolas, monospace",
                }}
              >
                {error.name}: {error.message}
              </pre>
            )}
            <div style={{ display: "flex", gap: 8 }}>
              <button
                onClick={this.handleReset}
                style={{
                  padding: "8px 16px",
                  border: "1px solid #497a69",
                  borderRadius: 6,
                  background: "#0d201a",
                  color: "#79d9b8",
                  fontSize: 13,
                  cursor: "pointer",
                }}
              >
                Retry
              </button>
              <button
                onClick={() => window.location.reload()}
                style={{
                  padding: "8px 16px",
                  border: "1px solid #2b3a35",
                  borderRadius: 6,
                  background: "#131c19",
                  color: "#a1aaa3",
                  fontSize: 13,
                  cursor: "pointer",
                }}
              >
                Reload page
              </button>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
