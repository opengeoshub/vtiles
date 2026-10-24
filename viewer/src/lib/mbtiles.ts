import initSqlJs, {
  type Database,
  type QueryResult,
  type SqlValue,
} from "sql.js";
import wasmUrl from "sql.js/dist/sql-wasm-browser.wasm?url";
import { asBytes, gunzipIfNeeded, toArrayBuffer, vectorLayerIds } from "./bytes";
import { boundsFromExtent, clampZoom, type Bounds } from "./bounds";
import type { AddProtocolAction } from "maplibre-gl";

export interface MbtilesSession {
  db: Database;
  table: string;
  vector: boolean;
}

export interface MbtilesInfo {
  session: MbtilesSession;
  bounds: Bounds | null;
  minzoom: number;
  maxzoom: number;
  vectorLayers: string[];
  attribution?: string;
}

let sqlPromise: ReturnType<typeof initSqlJs> | null = null;
let active: MbtilesSession | null = null;

function getSql() {
  sqlPromise ??= initSqlJs({ locateFile: () => wasmUrl });
  return sqlPromise;
}

function quoteIdent(name: string): string {
  return `"${name.replaceAll('"', '""')}"`;
}

function rowsOf(
  db: Database,
  sql: string,
  params: SqlValue[] = [],
): Record<string, SqlValue>[] {
  const statement = db.prepare(sql);
  try {
    statement.bind(params);
    const rows: Record<string, SqlValue>[] = [];
    while (statement.step()) rows.push(statement.getAsObject());
    return rows;
  } finally {
    statement.free();
  }
}

function columnsOf(db: Database, table: string): string[] {
  const escaped = quoteIdent(table);
  const pragma = db.exec(`PRAGMA table_info(${escaped})`);
  const first = pragma[0];
  if (first && first.values.length > 0) {
    return first.values.map((row) => String(row[1]));
  }
  try {
    const empty = db.exec(`SELECT * FROM ${escaped} LIMIT 0`);
    return empty[0]?.columns ?? [];
  } catch {
    return [];
  }
}

function detectTileTable(db: Database): string {
  const found: QueryResult[] = db.exec(`
    SELECT name, type
    FROM sqlite_master
    WHERE name = 'tiles' AND type IN ('table', 'view')
    LIMIT 1
  `);
  const row = found[0]?.values[0];
  if (!row) {
    throw new Error(
      'This MBTiles file has no "tiles" table or view.',
    );
  }
  const name = String(row[0]);
  const columns = columnsOf(db, name);
  const required = ["zoom_level", "tile_column", "tile_row", "tile_data"];
  if (!required.every((column) => columns.includes(column))) {
    throw new Error(
      'The "tiles" table must contain zoom_level, tile_column, tile_row, and tile_data.',
    );
  }
  return name;
}

function readMetadata(db: Database): Record<string, string> {
  const metadata: Record<string, string> = {};
  const exists = db.exec(`
    SELECT name FROM sqlite_master
    WHERE name = 'metadata' AND type IN ('table', 'view')
    LIMIT 1
  `);
  if (!exists[0]?.values.length) return metadata;
  try {
    for (const row of rowsOf(db, "SELECT name, value FROM metadata")) {
      metadata[String(row.name)] = String(row.value ?? "");
    }
  } catch (error) {
    console.warn("Could not read MBTiles metadata.", error);
  }
  return metadata;
}

function layerIdsFromMetadata(metadata: Record<string, string>): string[] {
  const ids: string[] = [];
  const collect = (value: unknown) => {
    if (!Array.isArray(value)) return;
    for (const item of value) {
      if (!item || typeof item !== "object") continue;
      const record = item as Record<string, unknown>;
      const id = record.id ?? record["source-layer"] ?? record.name;
      if (typeof id === "string" && id) ids.push(id);
    }
  };
  if (metadata.json) {
    try {
      const parsed = JSON.parse(metadata.json) as Record<string, unknown>;
      collect(parsed.vector_layers ?? parsed.layers);
    } catch {
      // Metadata json is optional.
    }
  }
  if (!ids.length && metadata.vector_layers) {
    try {
      collect(JSON.parse(metadata.vector_layers));
    } catch {
      // Ignore a metadata value that is not JSON.
    }
  }
  return ids;
}

function detectFormat(
  metadata: Record<string, string>,
  sample: Uint8Array | null,
): string {
  if (metadata.format) return metadata.format.toLowerCase();
  if (!sample || sample.length < 2) return "pbf";
  if (sample[0] === 0x89 && sample[1] === 0x50) return "png";
  if (sample[0] === 0xff && sample[1] === 0xd8) return "jpg";
  if (sample[0] === 0x1f && sample[1] === 0x8b) return "pbf";
  if (
    sample.length >= 4 &&
    sample[0] === 0x52 &&
    sample[1] === 0x49 &&
    sample[2] === 0x46 &&
    sample[3] === 0x46
  ) {
    return "webp";
  }
  return "pbf";
}

async function discoverLayers(
  db: Database,
  table: string,
): Promise<string[]> {
  const escaped = quoteIdent(table);
  let rows: Record<string, SqlValue>[] = [];
  try {
    rows = rowsOf(
      db,
      `SELECT tile_data FROM ${escaped}
       WHERE zoom_level = (SELECT MIN(zoom_level) FROM ${escaped})
       LIMIT 4`,
    );
  } catch (error) {
    console.warn("Could not sample MBTiles layers.", error);
    return [];
  }
  const ids = new Set<string>();
  for (const row of rows) {
    const bytes = asBytes(row.tile_data);
    if (!bytes) continue;
    for (const id of await vectorLayerIds(bytes)) ids.add(id);
  }
  return [...ids];
}

export async function openMbtilesBytes(bytes: Uint8Array): Promise<MbtilesInfo> {
  const SQL = await getSql();
  const db = new SQL.Database(bytes);
  try {
    const table = detectTileTable(db);
    const metadata = readMetadata(db);
    const escaped = quoteIdent(table);
    let sample: Uint8Array | null = null;
    try {
      const sampleRows = rowsOf(
        db,
        `SELECT tile_data FROM ${escaped} LIMIT 1`,
      );
      sample = asBytes(sampleRows[0]?.tile_data);
    } catch (error) {
      console.warn("Could not read a sample MBTiles tile.", error);
    }

    const format = detectFormat(metadata, sample);
    let vectorLayers = layerIdsFromMetadata(metadata);
    const image = ["png", "jpg", "jpeg", "webp", "gif", "avif"].includes(format);
    let vector =
      vectorLayers.length > 0 ||
      ["pbf", "mvt", "mvt.gz"].includes(format) ||
      (!image && !metadata.format);
    if (vector && vectorLayers.length === 0) {
      vectorLayers = await discoverLayers(db, table);
    }
    if (vector && vectorLayers.length === 0) {
      throw new Error(
        "Vector MBTiles were detected, but no vector layers were listed or found in a sample tile.",
      );
    }
    if (!vector) vectorLayers = [];

    let minzoom = clampZoom(metadata.minzoom, 0);
    let maxzoom = clampZoom(metadata.maxzoom, vector ? 14 : 18);
    if (!metadata.minzoom || !metadata.maxzoom) {
      try {
        const range = rowsOf(
          db,
          `SELECT MIN(zoom_level) AS minzoom, MAX(zoom_level) AS maxzoom FROM ${escaped}`,
        );
        if (!metadata.minzoom) minzoom = clampZoom(range[0]?.minzoom, minzoom);
        if (!metadata.maxzoom) maxzoom = clampZoom(range[0]?.maxzoom, maxzoom);
      } catch (error) {
        console.warn("Could not read MBTiles zoom range.", error);
      }
    }

    return {
      session: { db, table, vector },
      bounds: boundsFromExtent(metadata.bounds),
      minzoom,
      maxzoom: Math.max(minzoom, maxzoom),
      vectorLayers,
      attribution: metadata.attribution || undefined,
    };
  } catch (error) {
    try {
      db.close();
    } catch {
      // The database is already unusable.
    }
    throw error;
  }
}

export function adoptMbtiles(session: MbtilesSession | null): void {
  if (active && active !== session) {
    try {
      active.db.close();
    } catch (error) {
      console.warn("Could not close the previous MBTiles database.", error);
    }
  }
  active = session;
}

export function discardMbtiles(session: MbtilesSession | null): void {
  if (!session || session === active) return;
  try {
    session.db.close();
  } catch (error) {
    console.warn("Could not close an unused MBTiles database.", error);
  }
}

function tileCoordinates(url: string): { z: number; x: number; y: number } {
  const match = url.match(/(\d+)\/(-?\d+)\/(-?\d+)\/?$/);
  if (!match) throw new Error("Invalid MBTiles tile URL.");
  return { z: Number(match[1]), x: Number(match[2]), y: Number(match[3]) };
}

export const serveMbtilesTile: AddProtocolAction = async (params) => {
  if (!active) throw new Error("No MBTiles database is open.");
  const { z, x, y } = tileCoordinates(params.url);
  const max = 2 ** z - 1;
  if (x < 0 || y < 0 || x > max || y > max) {
    throw new Error("Tile not found");
  }
  // MBTiles stores TMS row numbers. MapLibre asks for XYZ.
  const tmsY = max - y;
  const escaped = quoteIdent(active.table);
  let rows: Record<string, SqlValue>[];
  try {
    rows = rowsOf(
      active.db,
      `SELECT tile_data FROM ${escaped}
       WHERE zoom_level = ? AND tile_column = ? AND tile_row = ?
       LIMIT 1`,
      [z, x, tmsY],
    );
  } catch (error) {
    console.warn("MBTiles tile query failed.", error);
    throw new Error("Tile not found");
  }
  const bytes = asBytes(rows[0]?.tile_data);
  if (!bytes) throw new Error("Tile not found");
  const data = active.vector ? await gunzipIfNeeded(bytes) : bytes;
  return { data: toArrayBuffer(data) };
};
