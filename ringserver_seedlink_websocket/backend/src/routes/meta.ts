import type { FastifyInstance } from "fastify";
import {
  clearMetaCache,
  getMetaCache,
  getSettings,
  putMetaCache,
  saveSettings,
} from "../db.js";

function scnlKey(net: string, sta: string, loc: string, cha: string) {
  return `${net}.${sta}.${loc || "--"}.${cha}`;
}

function parseSensitivity(xml: string): { sensitivity: number | null; units: string | null } {
  const sensMatch =
    xml.match(/<SensitivityValue>([\d.eE+-]+)<\/SensitivityValue>/) ||
    xml.match(/<InstrumentSensitivity>[\s\S]*?<Value>([\d.eE+-]+)<\/Value>/);
  const unitMatch =
    xml.match(/<InputUnits>[\s\S]*?<Name>([^<]+)<\/Name>/) ||
    xml.match(/<InstrumentSensitivity>[\s\S]*?<InputUnits>[\s\S]*?<Name>([^<]+)<\/Name>/);
  const sensitivity = sensMatch ? Number(sensMatch[1]) : null;
  return {
    sensitivity: Number.isFinite(sensitivity) ? sensitivity : null,
    units: unitMatch?.[1] ?? null,
  };
}

export async function metaRoutes(app: FastifyInstance) {
  app.get<{
    Querystring: { net?: string; sta?: string; loc?: string; cha?: string; refresh?: string };
  }>("/api/meta/sensitivity", async (req, reply) => {
    const { net, sta, cha } = req.query;
    const loc = req.query.loc ?? "";
    if (!net || !sta || !cha) {
      return reply.status(400).send({ error: "net_sta_cha_required" });
    }
    const scnl = scnlKey(net, sta, loc, cha);
    const cached = getMetaCache(scnl);
    if (cached && req.query.refresh !== "1") {
      return {
        scnl,
        sensitivity: cached.sensitivity,
        inputUnits: cached.input_units,
        cached: true,
        fetchedAt: cached.fetched_at,
        sourceUrl: cached.source_url,
      };
    }

    const base = getSettings().fdsnwsUrl.replace(/\/+$/, "");
    const params = new URLSearchParams({
      network: net,
      station: sta,
      location: loc === "--" || loc === "" ? "*" : loc,
      channel: cha,
      level: "channel",
      format: "xml",
    });
    const sourceUrl = `${base}/station/1/query?${params.toString()}`;
    try {
      const res = await fetch(sourceUrl, { signal: AbortSignal.timeout(12000) });
      const xml = await res.text();
      if (!res.ok) {
        return reply.status(502).send({ error: "fdsnws_failed", status: res.status, sourceUrl });
      }
      const parsed = parseSensitivity(xml);
      putMetaCache(scnl, parsed.sensitivity, parsed.units, sourceUrl);
      return {
        scnl,
        sensitivity: parsed.sensitivity,
        inputUnits: parsed.units,
        cached: false,
        fetchedAt: new Date().toISOString(),
        sourceUrl,
      };
    } catch (err) {
      return reply.status(502).send({
        error: "fdsnws_error",
        message: err instanceof Error ? err.message : String(err),
        sourceUrl,
      });
    }
  });

  app.post("/api/meta/clear-cache", async () => {
    clearMetaCache();
    return { ok: true };
  });

  app.put<{ Body: { fdsnwsUrl?: string; ringserverUrl?: string } }>(
    "/api/meta/urls",
    async (req) => {
      const body = req.body || {};
      const next = saveSettings({
        ...(body.fdsnwsUrl ? { fdsnwsUrl: body.fdsnwsUrl } : {}),
        ...(body.ringserverUrl ? { ringserverUrl: body.ringserverUrl } : {}),
      });
      if (body.fdsnwsUrl) clearMetaCache();
      return next;
    },
  );
}
