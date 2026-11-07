import { ref, shallowReactive, watch, type WatchSource } from "vue";

export interface Loadable<T> {
  readonly data: T | undefined;
  readonly error: unknown;
  readonly loading: boolean;
  reload: () => void;
}

/**
 * Loads data for a reactive key. A response for a key that is no longer current
 * (user switched to another Run meanwhile) is dropped, so it never overwrites
 * the current view; data of a previous key is cleared immediately on key change.
 * key null = nothing to load.
 */
export function useApi<T>(key: WatchSource<string | null>, fn: () => Promise<T>): Loadable<T> {
  const state = shallowReactive<{ data: T | undefined; error: unknown; loading: boolean; reload: () => void }>({
    data: undefined,
    error: undefined,
    loading: false,
    reload: () => nonce.value++,
  });
  const nonce = ref(0);
  let currentKey: string | null = null;
  watch(
    [key, nonce],
    ([k], _old, onCleanup) => {
      if (k !== currentKey) state.data = undefined;
      currentKey = k;
      state.error = undefined;
      if (k === null) {
        state.loading = false;
        return;
      }
      let alive = true;
      onCleanup(() => (alive = false));
      state.loading = true;
      fn().then(
        (data) => {
          if (!alive) return;
          state.data = data;
          state.loading = false;
        },
        (error: unknown) => {
          if (!alive) return;
          state.error = error;
          state.loading = false;
        },
      );
    },
    { immediate: true },
  );
  return state;
}

/**
 * Calls `tick` every `intervalMs()` while `active` is true. Ticks never overlap;
 * the loop restarts when `restartOn` changes and stops on scope dispose.
 */
export function usePolling(active: WatchSource<boolean>, intervalMs: () => number, tick: () => Promise<void>, restartOn?: WatchSource<unknown>): void {
  watch(
    restartOn ? [active, restartOn] : [active],
    ([on], _old, onCleanup) => {
      if (!on) return;
      let stopped = false;
      let timer: ReturnType<typeof setTimeout> | undefined;
      const loop = async () => {
        try {
          await tick();
        } finally {
          if (!stopped) timer = setTimeout(loop, intervalMs());
        }
      };
      void loop();
      onCleanup(() => {
        stopped = true;
        if (timer) clearTimeout(timer);
      });
    },
    { immediate: true },
  );
}
