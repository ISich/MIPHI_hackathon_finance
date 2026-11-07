import type { TableDataset } from "./model";
function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open("spr-tables", 1);
    request.onupgradeneeded = () => request.result.createObjectStore("datasets", { keyPath: "key" });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(new Error("Хранилище браузера недоступно. Разрешите сохранение данных для этого сайта."));
  });
}
async function transaction<T>(mode: IDBTransactionMode, run: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await database();
  return new Promise((resolve, reject) => {
    const tx = db.transaction("datasets", mode); const request = run(tx.objectStore("datasets"));
    tx.oncomplete = () => { db.close(); resolve(request.result); };
    tx.onabort = tx.onerror = () => { db.close(); reject(new Error("Не удалось сохранить таблицу. Проверьте свободное место и разрешения браузера.")); };
  });
}
const key = (owner: string, id: string) => JSON.stringify([owner, id]);
export async function loadDatasets(owner: string): Promise<TableDataset[]> {
  const values = await transaction("readonly", store => store.getAll());
  return values.filter(v => v.owner === owner).map(v => v.dataset as TableDataset).sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
}
export async function saveDataset(owner: string, dataset: TableDataset) {
  // Strip Vue proxies before IndexedDB's structured clone.
  await transaction("readwrite", store => store.put({ key: key(owner, dataset.id), owner, dataset: JSON.parse(JSON.stringify(dataset)) }));
}
export async function removeDataset(owner: string, id: string) { await transaction("readwrite", store => store.delete(key(owner, id))); }
