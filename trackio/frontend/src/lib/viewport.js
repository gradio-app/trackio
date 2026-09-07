/**
 * Viewport width helpers for the app shell.
 *
 * The sidebar is a fixed 290px column, which leaves almost nothing for the
 * page content on a phone, so it collapses itself on narrow viewports.
 */

export const NARROW_VIEWPORT_QUERY = "(max-width: 768px)";

export function watchNarrowViewport(onNarrow, win = window) {
  if (!win || typeof win.matchMedia !== "function") return () => {};
  const query = win.matchMedia(NARROW_VIEWPORT_QUERY);
  const handle = (event) => {
    if (event.matches) onNarrow();
  };
  handle(query);
  query.addEventListener("change", handle);
  return () => query.removeEventListener("change", handle);
}
