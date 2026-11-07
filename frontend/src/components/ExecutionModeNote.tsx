import { api } from "../api/instance";
import { useApi } from "../hooks/useApi";

/** Shows the server's execution mode up front, so a refusal is not a surprise. */
export function ExecutionModeNote() {
  const ready = useApi("ready", () => api.ready());
  const kinds = useApi("script-kinds", () => api.scriptKinds());
  const flag = kinds.data?.find((k) => k.custom_execution_enabled !== undefined)?.custom_execution_enabled;
  const mode = ready.data?.execution_mode ?? (flag === false ? "builtin-only" : flag ? "trusted-local" : undefined);
  if (!mode) return null;
  if (mode === "builtin-only" || flag === false)
    return (
      <div className="state state-disabled" role="note" data-testid="exec-mode">
        Сервер в режиме <code>builtin-only</code>: исполняются только встроенные процедуры и проверки. Пользовательский код будет сохранён,
        но запуск с ним backend отклонит (политика безопасности; включается администратором только для trusted-local на 127.0.0.1).
      </div>
    );
  return (
    <div className="state state-notready" role="note" data-testid="exec-mode">
      Режим исполнения сервера: <code>{mode}</code>. Пользовательский Python исполняется как доверенный локальный код — не изолированная песочница.
    </div>
  );
}
