import "./env.js";
import fs from "node:fs";
import path from "node:path";
import { DEFAULT_SETTINGS, type AppSettings } from "./defaults.js";

type MetaRow = {
  scnl: string;
  sensitivity: number | null;
  input_units: string | null;
  fetched_at: string;
  source_url: string;
};

type LayoutRow = {
  id: number;
  name: string;
  created_at: string;
  updated_at: string;
  payload_json: string;
};

type DbShape = {
  settings: AppSettings;
  layouts: LayoutRow[];
  meta_cache: Record<string, MetaRow>;
  nextLayoutId: number;
};

let state: DbShape;
let dbPath = "";

function persist() {
  fs.mkdirSync(path.dirname(dbPath), { recursive: true });
  fs.writeFileSync(dbPath, JSON.stringify(state, null, 2), "utf8");
}

function nextIdFrom(layouts: LayoutRow[], hint: number): number {
  const maxExisting = layouts.reduce((m, l) => Math.max(m, Number(l.id) || 0), 0);
  return Math.max(Number(hint) || 1, maxExisting + 1);
}

async function migrateFromSqliteIfNeeded(jsonPath: string) {
  const sqlitePath = jsonPath.replace(/\.json$/, ".db");
  if (!fs.existsSync(sqlitePath)) return;

  const existing: DbShape | null = fs.existsSync(jsonPath)
    ? (JSON.parse(fs.readFileSync(jsonPath, "utf8")) as DbShape)
    : null;
  // JSON에 이미 레이아웃이 있으면 덮어쓰지 않음
  if (existing?.layouts?.length) return;

  try {
    const { DatabaseSync } = await import("node:sqlite");
    const db = new DatabaseSync(sqlitePath, { readOnly: true });
    const layoutRows = db
      .prepare("SELECT id, name, created_at, updated_at, payload_json FROM layouts")
      .all() as Array<{
      id: number;
      name: string;
      created_at: string;
      updated_at: string;
      payload_json: string;
    }>;
    const settingsRow = db.prepare("SELECT payload_json FROM settings WHERE id = 1").get() as
      | { payload_json: string }
      | undefined;
    const metaRows = db
      .prepare(
        "SELECT scnl, sensitivity, input_units, fetched_at, source_url FROM meta_cache",
      )
      .all() as MetaRow[];
    db.close();

    if (!layoutRows.length && !settingsRow) return;

    const meta_cache: Record<string, MetaRow> = { ...(existing?.meta_cache || {}) };
    for (const m of metaRows) meta_cache[m.scnl] = m;

    const layouts: LayoutRow[] = layoutRows.map((r) => ({
      id: Number(r.id),
      name: String(r.name),
      created_at: String(r.created_at),
      updated_at: String(r.updated_at),
      payload_json: String(r.payload_json),
    }));

    const migrated: DbShape = {
      settings: settingsRow
        ? { ...DEFAULT_SETTINGS, ...(JSON.parse(settingsRow.payload_json) as AppSettings) }
        : { ...(existing?.settings || DEFAULT_SETTINGS) },
      layouts,
      meta_cache,
      nextLayoutId: nextIdFrom(layouts, 1),
    };
    fs.mkdirSync(path.dirname(jsonPath), { recursive: true });
    fs.writeFileSync(jsonPath, JSON.stringify(migrated, null, 2), "utf8");
  } catch {
    // 레거시 DB 이전 실패 시 JSON 경로로 계속 진행
  }
}

export async function initDb(databasePath: string): Promise<void> {
  dbPath = path.isAbsolute(databasePath)
    ? databasePath
    : path.resolve(process.cwd(), databasePath);
  // store as .json alongside requested path
  if (dbPath.endsWith(".db")) dbPath = dbPath.replace(/\.db$/, ".json");
  fs.mkdirSync(path.dirname(dbPath), { recursive: true });
  await migrateFromSqliteIfNeeded(dbPath);
  if (fs.existsSync(dbPath)) {
    state = JSON.parse(fs.readFileSync(dbPath, "utf8")) as DbShape;
    state.settings = { ...DEFAULT_SETTINGS, ...state.settings };
    state.layouts ||= [];
    state.meta_cache ||= {};
    state.nextLayoutId = nextIdFrom(state.layouts, state.nextLayoutId);
  } else {
    state = {
      settings: { ...DEFAULT_SETTINGS },
      layouts: [],
      meta_cache: {},
      nextLayoutId: 1,
    };
    persist();
  }
}

export function getSettings(): AppSettings {
  return {
    ...DEFAULT_SETTINGS,
    ...state.settings,
    waveformColors: {
      ...DEFAULT_SETTINGS.waveformColors,
      ...state.settings.waveformColors,
      channelColorMap: {
        ...DEFAULT_SETTINGS.waveformColors.channelColorMap,
        ...state.settings.waveformColors?.channelColorMap,
      },
      palette: [
        ...(state.settings.waveformColors?.palette ||
          DEFAULT_SETTINGS.waveformColors.palette),
      ],
    },
  };
}

export function saveSettings(partial: Partial<AppSettings>): AppSettings {
  state.settings = {
    ...state.settings,
    ...partial,
    waveformColors: partial.waveformColors
      ? { ...state.settings.waveformColors, ...partial.waveformColors }
      : state.settings.waveformColors,
  };
  persist();
  return getSettings();
}

export type { LayoutRow };

export function listLayouts(): LayoutRow[] {
  return [...state.layouts].sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1));
}

export function getLayout(id: number): LayoutRow | undefined {
  return state.layouts.find((l) => l.id === id);
}

export function createLayout(name: string, payload: unknown): LayoutRow {
  if (!state) throw new Error("DB not initialized");
  const now = new Date().toISOString();
  const id = nextIdFrom(state.layouts, state.nextLayoutId);
  const row: LayoutRow = {
    id,
    name,
    created_at: now,
    updated_at: now,
    payload_json: JSON.stringify(payload ?? {}),
  };
  state.layouts.push(row);
  state.nextLayoutId = id + 1;
  persist();
  return { ...row };
}

export function updateLayout(
  id: number,
  name: string,
  payload: unknown,
): LayoutRow | undefined {
  const row = getLayout(id);
  if (!row) return undefined;
  row.name = name;
  row.updated_at = new Date().toISOString();
  row.payload_json = JSON.stringify(payload ?? {});
  persist();
  return { ...row };
}

export function deleteLayout(id: number): boolean {
  const before = state.layouts.length;
  state.layouts = state.layouts.filter((l) => l.id !== id);
  persist();
  return state.layouts.length < before;
}

export function getMetaCache(scnl: string) {
  return state.meta_cache[scnl];
}

export function putMetaCache(
  scnl: string,
  sensitivity: number | null,
  inputUnits: string | null,
  sourceUrl: string,
) {
  state.meta_cache[scnl] = {
    scnl,
    sensitivity,
    input_units: inputUnits,
    fetched_at: new Date().toISOString(),
    source_url: sourceUrl,
  };
  persist();
}

export function clearMetaCache() {
  state.meta_cache = {};
  persist();
}
