import type { FastifyInstance } from "fastify";
import { getSettings, saveSettings } from "../db.js";
import { DURATION_MAX, MAX_PANELS_HARD, type AppSettings } from "../defaults.js";

function clampSettings(partial: Partial<AppSettings>): Partial<AppSettings> {
  const next = { ...partial };
  if (typeof next.durationSec === "number") {
    next.durationSec = Math.min(DURATION_MAX, Math.max(1, Math.floor(next.durationSec)));
  }
  if (typeof next.refreshIntervalMs === "number") {
    next.refreshIntervalMs = Math.min(10000, Math.max(50, Math.floor(next.refreshIntervalMs)));
  }
  if (typeof next.maxPanels === "number") {
    next.maxPanels = Math.min(MAX_PANELS_HARD, Math.max(1, Math.floor(next.maxPanels)));
  }
  // DataLink 전용 — SeedLink 선택 불가
  next.protocol = "datalink";
  if (next.amplitudeMode && next.amplitudeMode !== "raw" && next.amplitudeMode !== "physical") {
    delete next.amplitudeMode;
  }
  if (next.yScaleMode && next.yScaleMode !== "auto" && next.yScaleMode !== "uniform") {
    delete next.yScaleMode;
  }
  if (
    next.xAxisRightAnchor &&
    next.xAxisRightAnchor !== "now" &&
    next.xAxisRightAnchor !== "lastData"
  ) {
    delete next.xAxisRightAnchor;
  }
  return next;
}

export async function settingsRoutes(app: FastifyInstance) {
  app.get("/api/settings", async () => getSettings());

  app.put<{ Body: Partial<AppSettings> }>("/api/settings", async (req) => {
    const body = clampSettings(req.body || {});
    return saveSettings(body);
  });

  app.get("/api/settings/limits", async () => ({
    durationMax: DURATION_MAX,
    maxPanelsHard: MAX_PANELS_HARD,
    memoryWarnBytes: 512 * 1024 * 1024,
  }));

  app.post("/api/settings/test-ringserver", async (_req, reply) => {
    const { ringserverUrl } = getSettings();
    const target = `${ringserverUrl.replace(/\/+$/, "")}/streams/json`;
    try {
      const res = await fetch(target, { signal: AbortSignal.timeout(8000) });
      const text = await res.text();
      return {
        ok: res.ok,
        status: res.status,
        target,
        preview: text.slice(0, 400),
      };
    } catch (err) {
      return reply.status(502).send({
        ok: false,
        target,
        error: err instanceof Error ? err.message : String(err),
      });
    }
  });
}
