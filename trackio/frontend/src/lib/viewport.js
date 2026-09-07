/**
 * Viewport width helpers for the app shell.
 *
 * The sidebar is a fixed 290px column, which leaves almost nothing for the
 * page content on a phone, so it follows the viewport until the reader takes
 * charge of it themselves.
 */

export const NARROW_VIEWPORT_QUERY = "(max-width: 768px)";

export function watchNarrowViewport(onChange, win = window) {
  if (!win || typeof win.matchMedia !== "function") return () => {};
  const query = win.matchMedia(NARROW_VIEWPORT_QUERY);
  const handle = (event) => onChange(event.matches);
  handle(query);
  query.addEventListener("change", handle);
  return () => query.removeEventListener("change", handle);
}
