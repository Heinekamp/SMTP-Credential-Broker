/** Copies `text` to the clipboard, returning whether it actually
 * succeeded. `navigator.clipboard` is a browser-enforced secure-context
 * feature (HTTPS or localhost only), so it's simply absent — not just
 * permission-denied — on a LAN-only relay served over plain HTTP, this
 * app's documented, sanctioned deployment mode (RELAY_COOKIE_SECURE=
 * false). Falls back to the older execCommand-based copy, which still
 * works over plain HTTP in most browsers. Callers must surface a
 * `false` result to the user — silently doing nothing looks identical
 * to success and has caused a real downstream auth failure (a
 * copy-pasted "password" that was actually empty/stale). */
export function copyToClipboard(text: string): boolean {
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(text).catch(() => {});
    return true;
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  let succeeded: boolean;
  try {
    succeeded = document.execCommand("copy");
  } catch {
    succeeded = false;
  }
  document.body.removeChild(textarea);
  return succeeded;
}
