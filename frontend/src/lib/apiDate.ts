// Backend timestamps are naive UTC with no timezone suffix (see
// backend/app/core/clock.py's utcnow() and its comment on why). A plain
// `new Date(iso)` on a timezone-less ISO string is parsed by JS as *local*
// time, not UTC — silently skewing every relative/absolute timestamp in
// the UI by the viewer's UTC offset. Every API timestamp must go through
// this before becoming a Date.
export function parseApiDate(iso: string): Date {
  const hasTimezone = /[zZ]|[+-]\d{2}:?\d{2}$/.test(iso);
  return new Date(hasTimezone ? iso : `${iso}Z`);
}

/** "MM-DD HH:mm:ss" in the viewer's local time — the Dashboard's compact
 * recent-activity rows (design handoff screen 4) have no room for a full
 * locale-formatted timestamp or a year, unlike Mail Log's own detail rows. */
export function compactTimestamp(date: Date): string {
  const pad = (n: number) => n.toString().padStart(2, "0");
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}
