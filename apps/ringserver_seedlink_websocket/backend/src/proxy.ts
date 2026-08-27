import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import { WebSocketServer, WebSocket, type RawData } from "ws";
import { getSettings } from "./db.js";

function joinUrl(base: string, suffix: string): string {
  const b = base.replace(/\/+$/, "");
  const s = suffix.startsWith("/") ? suffix : `/${suffix}`;
  return `${b}${s}`;
}

async function proxyHttp(
  targetBase: string,
  req: FastifyRequest,
  reply: FastifyReply,
  stripPrefix: string,
) {
  const url = new URL(req.url, "http://localhost");
  const path = url.pathname.replace(stripPrefix, "") || "/";
  const target = joinUrl(targetBase, `${path}${url.search}`);
  try {
    const headers: Record<string, string> = {};
    for (const [k, v] of Object.entries(req.headers)) {
      if (v == null) continue;
      if (["host", "connection", "content-length"].includes(k.toLowerCase())) continue;
      headers[k] = Array.isArray(v) ? v.join(",") : v;
    }
    const init: RequestInit = {
      method: req.method,
      headers,
    };
    if (req.method !== "GET" && req.method !== "HEAD" && req.body != null) {
      init.body =
        typeof req.body === "string" ? req.body : JSON.stringify(req.body);
    }
    const res = await fetch(target, init);
    reply.status(res.status);
    res.headers.forEach((value, key) => {
      if (["transfer-encoding", "content-encoding"].includes(key.toLowerCase())) return;
      reply.header(key, value);
    });
    const buf = Buffer.from(await res.arrayBuffer());
    return reply.send(buf);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return reply.status(502).send({ error: "proxy_failed", message, target });
  }
}

export async function registerHttpProxies(app: FastifyInstance) {
  app.all("/ringserver", (req, reply) =>
    proxyHttp(getSettings().ringserverUrl, req, reply, "/ringserver"),
  );
  app.all("/ringserver/*", (req, reply) =>
    proxyHttp(getSettings().ringserverUrl, req, reply, "/ringserver"),
  );
  app.all("/fdsnws", (req, reply) =>
    proxyHttp(getSettings().fdsnwsUrl, req, reply, "/fdsnws"),
  );
  app.all("/fdsnws/*", (req, reply) =>
    proxyHttp(getSettings().fdsnwsUrl, req, reply, "/fdsnws"),
  );
}

function toBuffer(data: RawData): Buffer {
  if (Buffer.isBuffer(data)) return data;
  if (data instanceof ArrayBuffer) return Buffer.from(data);
  if (Array.isArray(data)) return Buffer.concat(data);
  return Buffer.from(data as Buffer);
}

function pickProtocol(
  requested: Set<string> | string[],
  path: string,
): string | false {
  const list = Array.isArray(requested) ? requested : [...requested];
  const prefer = path.includes("seedlink")
    ? ["SeedLink3.1", "SeedLink4.0"]
    : ["DataLink1.0", "DataLink1.1"];
  for (const p of prefer) {
    if (list.includes(p)) return p;
  }
  return list[0] || false;
}

/**
 * ringserver WebSocket 프록시 (폴백용 — 브라우저는 가능하면 직접 연결)
 * - permessage-deflate 비활성 (ringserver FIN/fragmentation 오류 방지)
 * - 단일 프레임으로 전달 (fin: true)
 * - DataLink는 BINARY 유지
 */
export function attachWsProxies(server: import("node:http").Server) {
  const wss = new WebSocketServer({
    noServer: true,
    perMessageDeflate: false,
    handleProtocols: (protocols, request) => {
      const url = request.url || "";
      return pickProtocol(protocols, url);
    },
  });

  server.on("upgrade", (request, socket, head) => {
    const host = request.headers.host || "localhost";
    const url = new URL(request.url || "/", `http://${host}`);
    if (!url.pathname.startsWith("/ringserver/")) {
      socket.destroy();
      return;
    }

    const suffix = url.pathname.replace(/^\/ringserver/, "") || "/";
    const base = getSettings().ringserverUrl.replace(/^http/, "ws");
    const target = joinUrl(base, `${suffix}${url.search}`);

    wss.handleUpgrade(request, socket, head, (client) => {
      const negotiated =
        client.protocol ||
        pickProtocol(
          (request.headers["sec-websocket-protocol"] || "")
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean),
          url.pathname,
        ) ||
        undefined;

      let upstream: WebSocket;
      try {
        upstream = negotiated
          ? new WebSocket(target, negotiated, { perMessageDeflate: false })
          : new WebSocket(target, { perMessageDeflate: false });
      } catch {
        client.close();
        return;
      }

      type Queued = { data: Buffer; isBinary: boolean };
      const queue: Queued[] = [];
      let upstreamOpen = false;

      const closeBoth = () => {
        try {
          client.close();
        } catch {
          /* ignore */
        }
        try {
          upstream.close();
        } catch {
          /* ignore */
        }
      };

      const forwardUp = (data: Buffer, isBinary: boolean) => {
        if (upstream.readyState !== WebSocket.OPEN) return;
        // DataLink/SeedLink: ringserver는 바이너리 프레임을 기대하는 경우가 많음
        // 텍스트로 온 경우도 Buffer로 보내고 opcode는 원본 유지
        if (isBinary) {
          upstream.send(data, { binary: true, fin: true, compress: false });
        } else {
          upstream.send(data.toString("utf8"), {
            binary: false,
            fin: true,
            compress: false,
          });
        }
      };

      client.on("message", (data, isBinary) => {
        const buf = toBuffer(data);
        if (!upstreamOpen) {
          queue.push({ data: buf, isBinary });
          return;
        }
        forwardUp(buf, isBinary);
      });

      upstream.on("open", () => {
        upstreamOpen = true;
        for (const q of queue) forwardUp(q.data, q.isBinary);
        queue.length = 0;
      });

      upstream.on("message", (data, isBinary) => {
        if (client.readyState !== WebSocket.OPEN) return;
        const buf = toBuffer(data);
        client.send(buf, { binary: isBinary, fin: true, compress: false });
      });

      client.on("close", closeBoth);
      upstream.on("close", closeBoth);
      client.on("error", closeBoth);
      upstream.on("error", closeBoth);
    });
  });
}
