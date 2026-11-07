import { api } from "./instance";
import type { Script } from "./types";

/** Save editor text (workspace) or the untouched uploaded file (source=file) as an immutable script snapshot. */
export function saveScript(kind: Script["kind"], name: string, code: string, file: File | null): Promise<Script> {
  return file ? api.uploadScript({ kind, name, file }) : api.createScript({ kind, name, code });
}
