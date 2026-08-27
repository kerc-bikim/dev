import { responsePngFilename } from "./pngFilename";

export { responsePngFilename };

function themeBackground(): string {
  const styles = getComputedStyle(document.documentElement);
  return styles.getPropertyValue("--bg").trim() || "#0d1117";
}

export async function exportResponsePng(
  container: HTMLElement,
  filename: string
): Promise<void> {
  const svg = container.querySelector("svg");
  if (!svg) return;
  const width = Number(svg.getAttribute("width")) || container.clientWidth;
  const height = Number(svg.getAttribute("height")) || container.clientHeight;
  const dpr = Math.min(3, Math.max(2, window.devicePixelRatio || 2));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(width * dpr);
  canvas.height = Math.round(height * dpr);
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.scale(dpr, dpr);
  ctx.fillStyle = themeBackground();
  ctx.fillRect(0, 0, width, height);
  const svgString = new XMLSerializer().serializeToString(svg);
  const blob = new Blob([svgString], { type: "image/svg+xml;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  try {
    const img = new Image();
    await new Promise<void>((resolve, reject) => {
      img.onload = () => resolve();
      img.onerror = () => reject(new Error("차트를 PNG로 저장하지 못했습니다"));
      img.src = url;
    });
    ctx.drawImage(img, 0, 0, width, height);
  } finally {
    URL.revokeObjectURL(url);
  }
  await new Promise<void>((resolve) => {
    canvas.toBlob((out) => {
      if (out) {
        const a = document.createElement("a");
        a.href = URL.createObjectURL(out);
        a.download = filename || responsePngFilename("VEL", []);
        a.click();
        URL.revokeObjectURL(a.href);
      }
      resolve();
    }, "image/png");
  });
}
