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
