import { useRef, useState, type ChangeEvent, type KeyboardEvent } from "react";

export const MAX_UPLOAD_BYTES = 256 * 1024;

/**
 * Plain textarea code editor (Tab inserts 4 spaces) + .py upload.
 * Code is never executed in the browser; it is only sent to the backend.
 */
export function PythonEditor({
  value,
  onChange,
  onFile,
  label = "Код Python",
}: {
  value: string;
  onChange: (code: string) => void;
  onFile?: (filename: string) => void;
  label?: string;
}) {
  const [fileError, setFileError] = useState<string | null>(null);
  const ref = useRef<HTMLTextAreaElement>(null);

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Tab" && !e.shiftKey) {
      e.preventDefault();
      const el = e.currentTarget;
      const { selectionStart: s, selectionEnd: end } = el;
      const next = value.slice(0, s) + "    " + value.slice(end);
      onChange(next);
      requestAnimationFrame(() => {
        if (ref.current) ref.current.selectionStart = ref.current.selectionEnd = s + 4;
      });
    }
  }

  async function onUpload(e: ChangeEvent<HTMLInputElement>) {
    setFileError(null);
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (!/^[A-Za-z0-9_\-]{1,80}\.py$/.test(file.name)) {
      setFileError("Нужен файл .py с простым именем (латиница, цифры, _ и -).");
      return;
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      setFileError(`Файл больше ${MAX_UPLOAD_BYTES / 1024} КБ.`);
      return;
    }
    const text = await file.text();
    onChange(text);
    onFile?.(file.name);
  }

  const lines = value.split("\n").length;
  return (
    <div className="editor">
      <label className="editor-label">
        {label}
        <textarea
          ref={ref}
          className="code"
          spellCheck={false}
          value={value}
          rows={Math.min(30, Math.max(12, lines + 1))}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={onKeyDown}
        />
      </label>
      <div className="editor-bar">
        <label className="file-btn">
          Загрузить .py
          <input type="file" accept=".py,text/x-python" onChange={onUpload} data-testid="py-upload" />
        </label>
        <span className="muted">{lines} строк, {new Blob([value]).size} байт</span>
      </div>
      {fileError ? (
        <div className="state state-error" role="alert">
          {fileError}
        </div>
      ) : null}
    </div>
  );
}
