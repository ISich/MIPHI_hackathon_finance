/** Determinate only when total is known; otherwise an indeterminate bar (no invented percent). */
export function Progress({ processed, total }: { processed?: number | null; total?: number | null }) {
  if (typeof total === "number" && total > 0 && typeof processed === "number") {
    const pct = Math.min(100, Math.round((processed / total) * 100));
    return (
      <div className="progress">
        <progress max={total} value={processed} aria-label="Прогресс" />
        <span>
          {processed} / {total} ({pct}%)
        </span>
      </div>
    );
  }
  return (
    <div className="progress">
      <progress aria-label="Прогресс (общее число неизвестно)" />
      <span>{typeof processed === "number" ? `обработано ${processed}, всего неизвестно` : "прогресс неизвестен"}</span>
    </div>
  );
}
