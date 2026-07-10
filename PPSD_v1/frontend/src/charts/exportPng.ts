/**
 * Composite a chart's WebGL canvas (if any) and its D3 SVG overlay into a
 * single PNG and trigger a download. Replaces the former server-side PNG.
 */
export async function exportChartPng(
  container: HTMLElement,
  filename: string
): Promise<void> {
  const svg = container.querySelector("svg");
  if (!svg) return;

  const width = Number(svg.getAttribute("width")) || container.clientWidth;
  const height = Number(svg.getAttribute("height")) || container.clientHeight;

  const out = document.createElement("canvas");
  const dpr = window.devicePixelRatio || 1;
  out.width = Math.round(width * dpr);
  out.height = Math.round(height * dpr);
  const ctx = out.getContext("2d");
  if (!ctx) return;
  ctx.scale(dpr, dpr);

  // white background
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, width, height);

  // WebGL heatmap canvas underlay (positioned via CSS left/top)
  const webglCanvas = container.querySelector("canvas") as HTMLCanvasElement | null;
  if (webglCanvas) {
    const left = parseFloat(webglCanvas.style.left || "0");
    const top = parseFloat(webglCanvas.style.top || "0");
    const w = parseFloat(webglCanvas.style.width || "0");
    const h = parseFloat(webglCanvas.style.height || "0");
    if (w > 0 && h > 0) {
      ctx.drawImage(webglCanvas, left, top, w, h);
    }
  }

  // SVG overlay on top
  const svgString = new XMLSerializer().serializeToString(svg);
  const svgBlob = new Blob([svgString], { type: "image/svg+xml;charset=utf-8" });
  const url = URL.createObjectURL(svgBlob);
  try {
    const img = new Image();
    await new Promise<void>((resolve, reject) => {
      img.onload = () => resolve();
      img.onerror = () => reject(new Error("Failed to rasterize SVG overlay"));
      img.src = url;
    });
    ctx.drawImage(img, 0, 0, width, height);
  } finally {
    URL.revokeObjectURL(url);
  }

  await new Promise<void>((resolve) => {
    out.toBlob((blob) => {
      if (blob) {
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = filename;
        a.click();
        URL.revokeObjectURL(a.href);
      }
      resolve();
    }, "image/png");
  });
}
