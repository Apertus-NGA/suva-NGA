import { Component, type ErrorInfo, type ReactNode } from "react";
import { useI18n } from "../lib/i18n";

type Props = { children: ReactNode; /** A new key (another view or ruling) clears a caught error. */ resetKey?: string };
type State = { error: Error | null; key: string | undefined };

/** Catches a rendering error in the main content: a short message and a reload button instead of a white screen. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, key: this.props.resetKey };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  static getDerivedStateFromProps(props: Props, state: State): Partial<State> | null {
    return props.resetKey !== state.key ? { error: null, key: props.resetKey } : null;
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("The page failed to render", error, info.componentStack);
  }

  render() {
    return this.state.error ? <Fallback /> : this.props.children;
  }
}

function Fallback() {
  const { t } = useI18n();
  return (
    <div role="alert" className="flex h-full flex-col items-center justify-center gap-4">
      <p className="font-serif text-[17px] text-ink">{t("app.loadError")}</p>
      <button
        type="button"
        onClick={() => window.location.reload()}
        className="h-8 rounded-md bg-ink px-3 text-[13px] font-medium text-white hover:bg-ink/85"
      >
        {t("app.retry")}
      </button>
    </div>
  );
}
