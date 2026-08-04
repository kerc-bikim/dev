import "./env.js";
import path from "node:path";
import Fastify from "fastify";
import cors from "@fastify/cors";
import { rootDir } from "./env.js";
import { initDb } from "./db.js";
import { registerHttpProxies, attachWsProxies } from "./proxy.js";
import { settingsRoutes } from "./routes/settings.js";
import { layoutsRoutes } from "./routes/layouts.js";
import { metaRoutes } from "./routes/meta.js";

const port = Number(process.env.PORT || 8787);
const databasePath = path.join(rootDir, "backend/data/app.json");
await initDb(databasePath);

const app = Fastify({ logger: true });
await app.register(cors, { origin: true });
await app.register(settingsRoutes);
await app.register(layoutsRoutes);
await app.register(metaRoutes);
await registerHttpProxies(app);

app.get("/api/health", async () => ({ ok: true }));

await app.listen({ port, host: "0.0.0.0" });
attachWsProxies(app.server);

console.log(`Backend listening on http://localhost:${port}`);
