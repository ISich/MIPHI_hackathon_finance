import type { ReactNode } from "react";
import { ApiError } from "../api/client";

/** Uniform error view: shows machine code, message and request id; distinguishes not-ready/forbidden/not-found. */
export function ErrorView({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  if (error instanceof ApiError) {
    let title = "Ошибка";
    let kind = "error";
    if (error.isNotReady) {
      title = "Ещё не готово";
      kind = "notready";
    } else if (error.isExecutionDisabled) {
      title = "Исполнение пользовательского Python выключено на сервере";
      kind = "disabled";
    } else if (error.isForbidden) {
      title = "Нет доступа";
      kind = "forbidden";
    } else if (error.isNotFound) {
      title = "Не найдено (или нет доступа)";
      kind = "notfound";
    }
    const details = Object.keys(error.details).length ? JSON.stringify(error.details, null, 2) : null;
    return (
      <div className={`state state-${kind}`} role="alert" data-error-code={error.code}>
        <strong>{title}</strong>
        <div>
          <code>{error.code}</code> {error.status ? `(HTTP ${error.status})` : null}: {error.message}
        </div>
        {details ? <pre className="details">{details}</pre> : null}
        {error.requestId ? <div className="muted">request_id: {error.requestId}</div> : null}
        {onRetry ? (
          <button type="button" onClick={onRetry}>
            Повторить
          </button>
        ) : null}
      </div>
    );
  }
  return (
    <div className="state state-error" role="alert">
      <strong>Ошибка</strong>
      <div>{error instanceof Error ? error.message : String(error)}</div>
    </div>
  );
}

export function Loading({ what = "Загрузка" }: { what?: string }) {
  return (
    <div className="state state-loading" role="status" aria-live="polite">
      {what}…
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="state state-empty">{children}</div>;
}

/** Renders loading / error / empty / content for a Loadable. */
export function Async<T>({
  value,
  children,
  isEmpty,
  empty,
  what,
}: {
  value: { data: T | undefined; error: unknown; loading: boolean; reload: () => void };
  children: (data: T) => ReactNode;
  isEmpty?: (data: T) => boolean;
  empty?: ReactNode;
  what?: string;
}) {
  if (value.error) return <ErrorView error={value.error} onRetry={value.reload} />;
  if (value.data === undefined) return value.loading ? <Loading what={what} /> : null;
  if (isEmpty && isEmpty(value.data)) return <Empty>{empty ?? "Пусто"}</Empty>;
  return <>{children(value.data)}</>;
}
