/** Polling intervals (ms). Mutable only so tests can shorten them. */
export const timing = {
  runPollMs: 1500,
  listPollMs: 3000,
  checkRunPollMs: 1500,
  /** Journal refresh of a finished Run while its monitor is open (later CheckRuns append events). */
  idleJournalPollMs: 5000,
};
