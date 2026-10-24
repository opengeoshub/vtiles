// Remote MBTiles are SQLite files. sql.js can run the same queries GeoLibre uses,
// but its Database constructor copies the whole file into memory. This reader
// fetches only the SQLite pages a tile lookup needs, over HTTP Range requests.

export interface SqliteMbtiles {
  metadata: Record<string, string>;
  minzoom: number | null;
  maxzoom: number | null;
  requests: number;
  bytesRead: number;
  readTile(zoom: number, column: number, row: number): Promise<Uint8Array | null>;
  sampleTile(): Promise<Uint8Array | null>;
  close(): void;
}

type SqlValue = number | string | Uint8Array | null;

interface SchemaObject {
  type: string;
  name: string;
  table: string;
  rootpage: number;
  sql: string;
}

const PAGE_CACHE = 256;

export async function openSqliteMbtiles(
  url: string,
  signal: AbortSignal,
): Promise<SqliteMbtiles> {
  const file = new RangeFile(url, signal);
  await file.open();
  const objects = await schemaObjects(file);
  const tiles = objects.find(
    (item) => item.name === "tiles" && (item.type === "table" || item.type === "view"),
  );
  if (!tiles) throw new Error('This MBTiles file has no "tiles" table.');
  const plan = resolveTiles(objects, tiles);
  const metadataObject = objects.find(
    (item) => item.name === "metadata" && item.type === "table",
  );
  const metadata = metadataObject ? await readMetadata(file, metadataObject) : {};
  const minzoom = await zoomBound(file, metadata, plan.indexRoot, plan.zoomColumn, "min");
  const maxzoom = await zoomBound(file, metadata, plan.indexRoot, plan.zoomColumn, "max");
  let closed = false;

  const ensureOpen = () => {
    if (closed) throw new Error("This MBTiles file is no longer open.");
  };

  return {
    metadata,
    minzoom,
    maxzoom,
    get requests() {
      return file.requests;
    },
    get bytesRead() {
      return file.bytesRead;
    },
    async readTile(zoom, column, row) {
      ensureOpen();
      return plan.read(file, zoom, column, row);
    },
    async sampleTile() {
      ensureOpen();
      return plan.sample(file);
    },
    close() {
      closed = true;
      file.close();
    },
  };
}

type IndexKey = number | string;

interface TilePlan {
  indexRoot: number;
  zoomColumn: number;
  read(file: RangeFile, zoom: number, column: number, row: number): Promise<Uint8Array | null>;
  sample(file: RangeFile): Promise<Uint8Array | null>;
}

function resolveTiles(objects: SchemaObject[], tiles: SchemaObject): TilePlan {
  if (tiles.type === "view") return tilesViewPlan(objects, tiles);
  return tilesTablePlan(objects, tiles);
}

function tilesTablePlan(objects: SchemaObject[], tiles: SchemaObject): TilePlan {
  if (/without\s+rowid/i.test(tiles.sql)) {
    throw new Error("This MBTiles file uses a WITHOUT ROWID table, which this viewer cannot read remotely.");
  }
  const columns = tableColumns(tiles.sql);
  const required = ["zoom_level", "tile_column", "tile_row", "tile_data"] as const;
  for (const name of required) {
    if (!columns.includes(name)) {
      throw new Error(
        'The "tiles" table must contain zoom_level, tile_column, tile_row, and tile_data.',
      );
    }
  }
  const index = findIndex(objects, tiles.name, required.slice(0, 3));
  const tileDataIndex = columns.indexOf("tile_data");
  return {
    indexRoot: index.rootpage,
    zoomColumn: index.columns.indexOf("zoom_level"),
    async read(file, zoom, column, row) {
      const rowid = await findIndexRowid(file, index.rootpage, indexKey(index.columns, zoom, column, row));
      if (rowid === null) return null;
      const record = await findTableRow(file, tiles.rootpage, rowid);
      const blob = record?.[tileDataIndex];
      return blob instanceof Uint8Array ? blob : null;
    },
    async sample(file) {
      const rowid = await firstIndexRowid(file, index.rootpage);
      if (rowid === null) return null;
      const record = await findTableRow(file, tiles.rootpage, rowid);
      const blob = record?.[tileDataIndex];
      return blob instanceof Uint8Array ? blob : null;
    },
  };
}

function tilesViewPlan(objects: SchemaObject[], tiles: SchemaObject): TilePlan {
  const mapImages =
    /from\s+map\b/i.test(tiles.sql) &&
    /join\s+images\b/i.test(tiles.sql) &&
    /images\.tile_id\s*=\s*map\.tile_id/i.test(tiles.sql);
  if (!mapImages) {
    throw new Error('This MBTiles file uses a "tiles" view this viewer cannot read remotely.');
  }
  const map = objects.find((item) => item.type === "table" && item.name === "map");
  const images = objects.find((item) => item.type === "table" && item.name === "images");
  if (!map || !images) {
    throw new Error('This MBTiles view needs "map" and "images" tables.');
  }
  const mapColumns = tableColumns(map.sql);
  const imageColumns = tableColumns(images.sql);
  const tileIdIndex = mapColumns.indexOf("tile_id");
  const blobIndex = imageColumns.indexOf("tile_data");
  if (tileIdIndex < 0 || blobIndex < 0) {
    throw new Error("This MBTiles view needs map.tile_id and images.tile_data.");
  }
  const mapIndex = findIndex(objects, "map", ["zoom_level", "tile_column", "tile_row"]);
  const imageIndex = findIndex(objects, "images", ["tile_id"]);

  const readBlob = async (file: RangeFile, mapRowid: number): Promise<Uint8Array | null> => {
    const mapRow = await findTableRow(file, map.rootpage, mapRowid);
    const tileId = mapRow?.[tileIdIndex];
    if (typeof tileId !== "string" && typeof tileId !== "number") return null;
    const imageRowid = await findIndexRowid(file, imageIndex.rootpage, [tileId]);
    if (imageRowid === null) return null;
    const imageRow = await findTableRow(file, images.rootpage, imageRowid);
    const blob = imageRow?.[blobIndex];
    return blob instanceof Uint8Array ? blob : null;
  };

  return {
    indexRoot: mapIndex.rootpage,
    zoomColumn: mapIndex.columns.indexOf("zoom_level"),
    async read(file, zoom, column, row) {
      const rowid = await findIndexRowid(
        file,
        mapIndex.rootpage,
        indexKey(mapIndex.columns, zoom, column, row),
      );
      if (rowid === null) return null;
      return readBlob(file, rowid);
    },
    async sample(file) {
      const rowid = await firstIndexRowid(file, mapIndex.rootpage);
      if (rowid === null) return null;
      return readBlob(file, rowid);
    },
  };
}

function findIndex(
  objects: SchemaObject[],
  table: string,
  required: string[],
): { rootpage: number; columns: string[] } {
  const found = objects
    .filter((item) => item.type === "index" && item.table === table && item.rootpage > 0)
    .map((item) => ({ rootpage: item.rootpage, columns: indexedColumns(item.sql) }))
    .find((item) => required.every((name) => item.columns.includes(name)));
  if (!found) {
    throw new Error(
      "This MBTiles file has no zoom/column/row index, so it cannot be read without downloading the whole file.",
    );
  }
  return found;
}

function indexKey(columns: string[], zoom: number, column: number, row: number): IndexKey[] {
  return columns.map((name) => {
    if (name === "zoom_level") return zoom;
    if (name === "tile_column") return column;
    if (name === "tile_row") return row;
    throw new Error(`The MBTiles index includes an unsupported column "${name}".`);
  });
}

async function firstIndexRowid(file: RangeFile, root: number): Promise<number | null> {
  const key = await edgeIndexKey(file, root, "first");
  const rowid = key?.[key.length - 1];
  return typeof rowid === "number" ? rowid : null;
}

class RangeFile {
  pageSize = 0;
  pageCount = 0;
  reserved = 0;
  requests = 0;
  bytesRead = 0;
  encoding: "utf-8" | "utf-16le" | "utf-16be" = "utf-8";
  private readonly cache = new Map<number, Uint8Array>();
  private readonly order: number[] = [];
  private readonly inflight = new Map<number, Promise<Uint8Array>>();
  private closed = false;

  constructor(
    private readonly url: string,
    private readonly signal: AbortSignal,
  ) {}

  async open(): Promise<void> {
    const header = await this.bytes(0, 100);
    const magic = new TextDecoder().decode(header.subarray(0, 15));
    if (magic !== "SQLite format 3") {
      throw new Error("This URL is not an MBTiles SQLite database.");
    }
    const view = dataView(header);
    let pageSize = view.getUint16(16);
    if (pageSize === 1) pageSize = 65536;
    this.pageSize = pageSize;
    this.pageCount = view.getUint32(28);
    this.reserved = header[20];
    const encoding = view.getUint32(56);
    if (encoding === 1) this.encoding = "utf-8";
    else if (encoding === 2) this.encoding = "utf-16le";
    else if (encoding === 3) this.encoding = "utf-16be";
    else throw new Error("This MBTiles file uses an unknown SQLite text encoding.");
  }

  async readPages(first: number, count: number): Promise<{ bytes: Uint8Array; count: number }> {
    const available = Math.min(count, this.pageCount - first + 1);
    if (available < 1) throw new Error("The MBTiles page is outside the file.");
    const bytes = await this.bytes((first - 1) * this.pageSize, available * this.pageSize);
    return { bytes, count: available };
  }

  async page(number: number): Promise<Uint8Array> {
    if (this.closed) throw new Error("This MBTiles file is no longer open.");
    const cached = this.cache.get(number);
    if (cached) return cached;
    let pending = this.inflight.get(number);
    if (!pending) {
      const start = (number - 1) * this.pageSize;
      pending = this.bytes(start, this.pageSize).then((bytes) => {
        this.inflight.delete(number);
        this.remember(number, bytes);
        return bytes;
      });
      this.inflight.set(number, pending);
    }
    return pending;
  }

  close(): void {
    this.closed = true;
    this.cache.clear();
    this.order.length = 0;
    this.inflight.clear();
  }

  private remember(number: number, bytes: Uint8Array): void {
    this.cache.set(number, bytes);
    this.order.push(number);
    while (this.order.length > PAGE_CACHE) {
      const oldest = this.order.shift();
      if (oldest !== undefined) this.cache.delete(oldest);
    }
  }

  private async bytes(start: number, length: number): Promise<Uint8Array> {
    const response = await fetch(this.url, {
      headers: { Range: `bytes=${start}-${start + length - 1}` },
      signal: this.signal,
    });
    if (response.status !== 206) {
      await response.body?.cancel();
      throw new Error(
        `This MBTiles host must support byte-range requests so the file is not downloaded whole (HTTP ${response.status}).`,
      );
    }
    const data = new Uint8Array(await response.arrayBuffer());
    if (data.byteLength !== length) {
      throw new Error("The MBTiles host returned an incomplete byte range.");
    }
    this.requests += 1;
    this.bytesRead += data.byteLength;
    return data;
  }
}

async function schemaObjects(file: RangeFile): Promise<SchemaObject[]> {
  const rows = await walkTable(file, 1);
  return rows.map((row) => ({
    type: String(row[0] ?? ""),
    name: String(row[1] ?? ""),
    table: String(row[2] ?? ""),
    rootpage: typeof row[3] === "number" ? row[3] : 0,
    sql: typeof row[4] === "string" ? row[4] : "",
  }));
}

async function readMetadata(
  file: RangeFile,
  object: SchemaObject,
): Promise<Record<string, string>> {
  const columns = tableColumns(object.sql);
  const nameIndex = columns.indexOf("name");
  const valueIndex = columns.indexOf("value");
  if (nameIndex < 0 || valueIndex < 0) return {};
  const metadata: Record<string, string> = {};
  for (const row of await walkTable(file, object.rootpage)) {
    const name = row[nameIndex];
    if (typeof name !== "string" || !name) continue;
    const value = row[valueIndex];
    metadata[name] = value == null ? "" : String(value);
  }
  return metadata;
}

async function zoomBound(
  file: RangeFile,
  metadata: Record<string, string>,
  indexRoot: number,
  zoomColumn: number,
  edge: "min" | "max",
): Promise<number | null> {
  const listed = Number(metadata[edge === "min" ? "minzoom" : "maxzoom"]);
  if (Number.isFinite(listed)) return listed;
  const key = await edgeIndexKey(file, indexRoot, edge === "min" ? "first" : "last");
  const zoom = key?.[zoomColumn];
  return typeof zoom === "number" ? zoom : null;
}

async function walkTable(file: RangeFile, pageNumber: number): Promise<SqlValue[][]> {
  const rows: SqlValue[][] = [];
  await collectTable(file, pageNumber, rows);
  return rows;
}

async function collectTable(
  file: RangeFile,
  pageNumber: number,
  rows: SqlValue[][],
): Promise<void> {
  const page = await file.page(pageNumber);
  const info = pageInfo(page, pageNumber);
  if (info.kind === 0x0d) {
    for (const pointer of cellPointers(page, info)) {
      rows.push(await readLeafRow(file, page, pointer));
    }
    return;
  }
  if (info.kind === 0x05) {
    for (const pointer of cellPointers(page, info)) {
      await collectTable(file, readUint32(page, pointer), rows);
    }
    await collectTable(file, info.right, rows);
    return;
  }
  throw new Error("Unexpected SQLite page while reading an MBTiles table.");
}

async function findTableRow(
  file: RangeFile,
  root: number,
  rowid: number,
): Promise<SqlValue[] | null> {
  let pageNumber = root;
  for (let depth = 0; depth < 64; depth += 1) {
    const page = await file.page(pageNumber);
    const info = pageInfo(page, pageNumber);
    if (info.kind === 0x0d) {
      for (const pointer of cellPointers(page, info)) {
        const id = readVarint(page, readVarint(page, pointer).next);
        if (id.value === rowid) return readLeafRow(file, page, pointer);
      }
      return null;
    }
    if (info.kind === 0x05) {
      let next = info.right;
      for (const pointer of cellPointers(page, info)) {
        const child = readUint32(page, pointer);
        const key = readVarint(page, pointer + 4);
        if (rowid <= key.value) {
          next = child;
          break;
        }
      }
      pageNumber = next;
      continue;
    }
    throw new Error("Unexpected SQLite page while reading an MBTiles row.");
  }
  throw new Error("The MBTiles table is too deep to search.");
}

async function findIndexRowid(
  file: RangeFile,
  root: number,
  key: IndexKey[],
): Promise<number | null> {
  let pageNumber = root;
  for (let depth = 0; depth < 64; depth += 1) {
    const page = await file.page(pageNumber);
    const info = pageInfo(page, pageNumber);
    if (info.kind === 0x0a) {
      for (const pointer of cellPointers(page, info)) {
        const values = parseRecord(await indexLeafPayload(file, page, pointer), file.encoding);
        if (compareKey(key, values) === 0) return lastNumber(values);
      }
      return null;
    }
    if (info.kind === 0x02) {
      let next = info.right;
      for (const pointer of cellPointers(page, info)) {
        const child = readUint32(page, pointer);
        const values = parseRecord(await indexInteriorPayload(file, page, pointer), file.encoding);
        const compared = compareKey(key, values);
        if (compared < 0) {
          next = child;
          break;
        }
        if (compared === 0) return lastNumber(values);
      }
      pageNumber = next;
      continue;
    }
    throw new Error("Unexpected SQLite page while reading the MBTiles index.");
  }
  throw new Error("The MBTiles index is too deep to search.");
}

async function edgeIndexKey(
  file: RangeFile,
  root: number,
  edge: "first" | "last",
): Promise<SqlValue[] | null> {
  let pageNumber = root;
  for (let depth = 0; depth < 64; depth += 1) {
    const page = await file.page(pageNumber);
    const info = pageInfo(page, pageNumber);
    const pointers = cellPointers(page, info);
    if (info.kind === 0x0a) {
      if (!pointers.length) return null;
      const pointer = edge === "first" ? pointers[0] : pointers[pointers.length - 1];
      return parseRecord(await indexLeafPayload(file, page, pointer), file.encoding);
    }
    if (info.kind === 0x02) {
      if (edge === "last") {
        pageNumber = info.right;
        continue;
      }
      pageNumber = pointers.length ? readUint32(page, pointers[0]) : info.right;
      continue;
    }
    throw new Error("Unexpected SQLite page while reading the MBTiles index.");
  }
  return null;
}

async function readLeafRow(
  file: RangeFile,
  page: Uint8Array,
  pointer: number,
): Promise<SqlValue[]> {
  const size = readVarint(page, pointer);
  const rowid = readVarint(page, size.next);
  const payload = await assemblePayload(file, page, rowid.next, size.value, "table");
  return parseRecord(payload, file.encoding);
}

async function indexLeafPayload(
  file: RangeFile,
  page: Uint8Array,
  pointer: number,
): Promise<Uint8Array> {
  const size = readVarint(page, pointer);
  return assemblePayload(file, page, size.next, size.value, "index");
}

async function indexInteriorPayload(
  file: RangeFile,
  page: Uint8Array,
  pointer: number,
): Promise<Uint8Array> {
  const size = readVarint(page, pointer + 4);
  return assemblePayload(file, page, size.next, size.value, "index");
}

async function assemblePayload(
  file: RangeFile,
  page: Uint8Array,
  start: number,
  size: number,
  kind: "table" | "index",
): Promise<Uint8Array> {
  const local = localPayloadBytes(file.pageSize - file.reserved, size, kind);
  if (size <= local) return page.slice(start, start + size);
  const head = page.slice(start, start + local);
  const overflow = readUint32(page, start + local);
  const payload = new Uint8Array(size);
  payload.set(head, 0);
  let filled = head.length;
  let next = overflow;
  const usable = file.pageSize - file.reserved;
  const pageSize = file.pageSize;
  while (next !== 0 && filled < size) {
    const pagesNeeded = Math.ceil((size - filled) / (usable - 4));
    const window = Math.min(32, Math.max(1, pagesNeeded));
    const block = await file.readPages(next, window);
    let pageNumber = next;
    for (let index = 0; index < block.count && filled < size; index += 1) {
      const overflowPage = block.bytes.subarray(index * pageSize, (index + 1) * pageSize);
      const following = readUint32(overflowPage, 0);
      const chunk = overflowPage.subarray(4, usable);
      const take = Math.min(chunk.length, size - filled);
      payload.set(chunk.subarray(0, take), filled);
      filled += take;
      pageNumber = following;
      if (following !== next + index + 1) break;
    }
    next = pageNumber;
  }
  if (filled < size) throw new Error("The MBTiles tile payload is truncated.");
  return payload;
}

function localPayloadBytes(usable: number, size: number, kind: "table" | "index"): number {
  const maxLocal =
    kind === "table" ? usable - 35 : Math.floor(((usable - 12) * 64) / 255) - 23;
  if (size <= maxLocal) return size;
  const minLocal = Math.floor(((usable - 12) * 32) / 255) - 23;
  let local = minLocal + ((size - minLocal) % (usable - 4));
  if (local > maxLocal) local = minLocal;
  return local;
}

interface PageHeader {
  kind: number;
  cells: number;
  right: number;
  headerEnd: number;
}

function pageInfo(page: Uint8Array, pageNumber: number): PageHeader {
  const offset = pageNumber === 1 ? 100 : 0;
  const kind = page[offset];
  const interior = kind === 0x02 || kind === 0x05;
  const view = dataView(page);
  return {
    kind,
    cells: view.getUint16(offset + 3),
    right: interior ? view.getUint32(offset + 8) : 0,
    headerEnd: offset + (interior ? 12 : 8),
  };
}

function cellPointers(page: Uint8Array, info: PageHeader): number[] {
  const view = dataView(page);
  const pointers: number[] = [];
  for (let index = 0; index < info.cells; index += 1) {
    pointers.push(view.getUint16(info.headerEnd + index * 2));
  }
  return pointers;
}

function parseRecord(
  payload: Uint8Array,
  encoding: "utf-8" | "utf-16le" | "utf-16be",
): SqlValue[] {
  const header = readVarint(payload, 0);
  const types: number[] = [];
  let cursor = header.next;
  while (cursor < header.value) {
    const serial = readVarint(payload, cursor);
    types.push(serial.value);
    cursor = serial.next;
  }
  const values: SqlValue[] = [];
  let body = header.value;
  for (const serial of types) {
    const decoded = readSerial(payload, body, serial, encoding);
    values.push(decoded.value);
    body = decoded.next;
  }
  return values;
}

function readSerial(
  payload: Uint8Array,
  offset: number,
  serial: number,
  encoding: "utf-8" | "utf-16le" | "utf-16be",
): { value: SqlValue; next: number } {
  if (serial === 0) return { value: null, next: offset };
  if (serial === 8) return { value: 0, next: offset };
  if (serial === 9) return { value: 1, next: offset };
  if (serial >= 1 && serial <= 6) {
    const size = [0, 1, 2, 3, 4, 6, 8][serial];
    return { value: readSigned(payload, offset, size), next: offset + size };
  }
  if (serial === 7) {
    return { value: dataView(payload).getFloat64(offset), next: offset + 8 };
  }
  if (serial >= 12 && serial % 2 === 0) {
    const size = (serial - 12) / 2;
    return { value: payload.slice(offset, offset + size), next: offset + size };
  }
  if (serial >= 13 && serial % 2 === 1) {
    const size = (serial - 13) / 2;
    return {
      value: new TextDecoder(encoding).decode(payload.subarray(offset, offset + size)),
      next: offset + size,
    };
  }
  throw new Error("This MBTiles file contains an unsupported SQLite value.");
}

function compareKey(key: IndexKey[], values: SqlValue[]): number {
  for (let index = 0; index < key.length; index += 1) {
    const order = comparePart(key[index], values[index]);
    if (order !== 0) return order;
  }
  return 0;
}

function comparePart(wanted: IndexKey, stored: SqlValue): number {
  if (typeof wanted === "number" && typeof stored === "number") {
    if (wanted === stored) return 0;
    return wanted < stored ? -1 : 1;
  }
  if (typeof wanted === "string" && typeof stored === "string") {
    if (wanted === stored) return 0;
    return wanted < stored ? -1 : 1;
  }
  const wantedKind = typeof wanted === "number" ? 1 : 2;
  const storedKind = typeof stored === "number" ? 1 : typeof stored === "string" ? 2 : 3;
  return wantedKind < storedKind ? -1 : 1;
}

function lastNumber(values: SqlValue[]): number | null {
  const value = values[values.length - 1];
  return typeof value === "number" ? value : null;
}

function readVarint(bytes: Uint8Array, offset: number): { value: number; next: number } {
  let value = 0;
  for (let index = 0; index < 9; index += 1) {
    const byte = bytes[offset + index];
    if (index === 8) return { value: value * 256 + byte, next: offset + 9 };
    value = value * 128 + (byte & 0x7f);
    if ((byte & 0x80) === 0) return { value, next: offset + index + 1 };
  }
  throw new Error("Invalid SQLite varint.");
}

function readUint32(bytes: Uint8Array, offset: number): number {
  return dataView(bytes).getUint32(offset);
}

function readSigned(bytes: Uint8Array, offset: number, size: number): number {
  if (size === 8) return Number(dataView(bytes).getBigInt64(offset));
  let value = 0;
  for (let index = 0; index < size; index += 1) value = value * 256 + bytes[offset + index];
  const sign = 2 ** (size * 8 - 1);
  if (value >= sign) value -= sign * 2;
  return value;
}

function dataView(bytes: Uint8Array): DataView {
  return new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
}

function tableColumns(sql: string): string[] {
  const open = sql.indexOf("(");
  const close = sql.lastIndexOf(")");
  if (open < 0 || close <= open) return [];
  const columns: string[] = [];
  for (const part of splitSqlList(sql.slice(open + 1, close))) {
    const trimmed = part.trim();
    if (!trimmed || /^(primary|unique|constraint|foreign|check)\b/i.test(trimmed)) continue;
    columns.push(unquote(trimmed.split(/\s+/)[0] ?? ""));
  }
  return columns.filter(Boolean);
}

function indexedColumns(sql: string): string[] {
  const match = /\bon\s+\S+\s*\(([^)]*)\)/i.exec(sql);
  if (!match) return [];
  return match[1]
    .split(",")
    .map((part) => unquote((part.trim().split(/\s+/)[0] ?? "")))
    .filter(Boolean);
}

function splitSqlList(body: string): string[] {
  const parts: string[] = [];
  let start = 0;
  let depth = 0;
  for (let index = 0; index < body.length; index += 1) {
    const char = body[index];
    if (char === "(") depth += 1;
    else if (char === ")") depth -= 1;
    else if (char === "," && depth === 0) {
      parts.push(body.slice(start, index));
      start = index + 1;
    }
  }
  parts.push(body.slice(start));
  return parts;
}

function unquote(token: string): string {
  return token.replace(/^[`"[]|[`"\]]$/g, "");
}
