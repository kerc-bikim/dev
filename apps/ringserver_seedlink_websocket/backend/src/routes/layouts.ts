import type { FastifyInstance } from "fastify";
import {
  createLayout,
  deleteLayout,
  getLayout,
  listLayouts,
  updateLayout,
} from "../db.js";

export async function layoutsRoutes(app: FastifyInstance) {
  app.get("/api/layouts", async () =>
    listLayouts().map((row) => ({
      id: row.id,
      name: row.name,
      createdAt: row.created_at,
      updatedAt: row.updated_at,
      payload: JSON.parse(row.payload_json),
    })),
  );

  app.get<{ Params: { id: string } }>("/api/layouts/:id", async (req, reply) => {
    const row = getLayout(Number(req.params.id));
    if (!row) return reply.status(404).send({ error: "not_found" });
    return {
      id: row.id,
      name: row.name,
      createdAt: row.created_at,
      updatedAt: row.updated_at,
      payload: JSON.parse(row.payload_json),
    };
  });

  app.post<{ Body: { name: string; payload: unknown } }>(
    "/api/layouts",
    async (req, reply) => {
      const name = (req.body?.name || "").trim();
      if (!name) return reply.status(400).send({ error: "name_required" });
      const row = createLayout(name, req.body?.payload ?? {});
      if (!row) return reply.status(500).send({ error: "create_failed" });
      return {
        id: row.id,
        name: row.name,
        createdAt: row.created_at,
        updatedAt: row.updated_at,
        payload: JSON.parse(row.payload_json),
      };
    },
  );

  app.put<{ Params: { id: string }; Body: { name: string; payload: unknown } }>(
    "/api/layouts/:id",
    async (req, reply) => {
      const name = (req.body?.name || "").trim();
      if (!name) return reply.status(400).send({ error: "name_required" });
      const row = updateLayout(Number(req.params.id), name, req.body?.payload ?? {});
      if (!row) return reply.status(404).send({ error: "not_found" });
      return {
        id: row.id,
        name: row.name,
        createdAt: row.created_at,
        updatedAt: row.updated_at,
        payload: JSON.parse(row.payload_json),
      };
    },
  );

  app.delete<{ Params: { id: string } }>("/api/layouts/:id", async (req, reply) => {
    const ok = deleteLayout(Number(req.params.id));
    if (!ok) return reply.status(404).send({ error: "not_found" });
    return { ok: true };
  });
}
