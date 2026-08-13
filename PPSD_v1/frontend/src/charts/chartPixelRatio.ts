/**
 * Backing-store pixel ratio for chart canvases / PNG export.
 * Floors at 2× so charts stay sharp on low-DPR displays; caps to avoid
 * excessive GPU memory on high-DPI screens.
 */
export function chartPixelRatio(cap = 3): number {
  const dpr = typeof window !== "undefined" ? window.devicePixelRatio || 1 : 1;
  return Math.min(Math.max(dpr, 2), cap);
}
