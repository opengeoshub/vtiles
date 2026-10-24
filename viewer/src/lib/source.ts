import type {
  RasterSourceSpecification,
  StyleSpecification,
  VectorSourceSpecification,
} from "@maplibre/maplibre-gl-style-spec";
import { PMTiles, TileType, type Header } from "pmtiles";
import { TilePackage } from "maplibre-tilepackage-protocol";
import {
  boundsFromExtent,
  clampZoom,
  lonLatBounds,
  type Bounds,
} from "./bounds";
import { looksLikeImage, vectorLayerIds } from "./bytes";
import {
  discardMbtiles,
  openMbtilesBytes,
  type MbtilesSession,
} from "./mbtiles";
import {
  discardProtocolKeys,
  holdPackage,
  holdPmtiles,
  packageFromFile,
  pmtilesFromFile,
} from "./protocols";

export type TileFormat =
  | "PMTiles"
  | "MBTiles"
  | "TileJSON"
  | "XYZ"
  | "VTPK"
  | "TPKX";

export interface LoadedSource {
  name: string;
  format: TileFormat;
  vector: boolean;
  bounds: Bounds | null;
  center: [number, number] | null;
  zoom: number | null;
  minzoom: number;
  maxzoom: number;
  vectorLayers: string[];
  attribution?: string;
  source: VectorSourceSpecification | RasterSourceSpecification | null;
  packageStyle: StyleSpecification | null;
  mbtiles: MbtilesSession | null;
  pmtilesKey: string | null;
  packageKey: string | null;
  note?: string;
}

type TileSource = VectorSourceSpecification | RasterSourceSpecification;

export function discardLoaded(loaded: LoadedSource, token: number): void {
  discardMbtiles(loaded.mbtiles);
  discardProtocolKeys(loaded.pmtilesKey, loaded.packageKey, token);
}

export async function loadFile(file: File, token: number): Promise<LoadedSource> {
  const name = file.name;
  const kind = kindFromName(name);
  if (kind === "pmtiles") return finishPmtiles(pmtilesFromFile(file), name, token);
  if (kind === "mbtiles") {
    const bytes = new Uint8Array(await file.arrayBuffer());
    return finishMbtiles(bytes, name);
  }
  if (kind === "vtpk") {
    return finishPackage(packageFromFile(file), name, token);
  }
  const text = await file.text();
  return finishTileJson(parseJson(text), name, null);
}

export async function loadRemote(
  input: string,
  token: number,
  signal: AbortSignal,
  onStatus?: (message: string) => void,
): Promise<LoadedSource> {
  const target = classifyRemote(input);
  if (target.kind === "xyz") return finishXyz(target.href, signal);
  if (target.kind === "pmtiles") {
    return finishPmtiles(new PMTiles(target.href), nameFromUrl(target.href), token);
  }
  if (target.kind === "mbtiles") {
    const name = nameFromUrl(target.href);
    onStatus?.(`Downloading ${name}…`);
    const bytes = await download(target.href, signal, (size) => {
      onStatus?.(`Downloading ${name} (${size})…`);
    });
    return finishMbtiles(bytes, name);
  }
  if (target.kind === "vtpk") {
    return finishPackage(new TilePackage(target.href), nameFromUrl(target.href), token);
  }
  if (target.kind === "tilejson") {
    return finishTileJson(
      await downloadJson(target.href, signal),
      nameFromUrl(target.href),
      target.href,
      signal,
    );
  }
  return loadUnknown(target.href, token, signal);
}

function kindFromName(name: string): "pmtiles" | "mbtiles" | "vtpk" | "tilejson" {
  const lower = name.toLowerCase();
  if (lower.endsWith(".pmtiles")) return "pmtiles";
  if (lower.endsWith(".mbtiles")) return "mbtiles";
  if (lower.endsWith(".vtpk") || lower.endsWith(".tpkx")) return "vtpk";
  if (lower.endsWith(".json")) return "tilejson";
  throw new Error("Open a .pmtiles, .mbtiles, .json, .vtpk, or .tpkx file.");
}

function classifyRemote(input: string): { kind: string; href: string } {
  const trimmed = input.trim();
  if (!trimmed) throw new Error("Enter a URL.");
  const tileTemplate =
    trimmed.includes("{z}") &&
    trimmed.includes("{x}") &&
    (trimmed.includes("{y}") || trimmed.includes("{-y}"));
  if (tileTemplate) {
    if (!/^https?:\/\//i.test(trimmed)) {
      throw new Error("A tile template has to be an http(s) URL.");
    }
    return { kind: "xyz", href: trimmed };
  }

  let url: URL;
  try {
    url = new URL(archiveUrl(trimmed), window.location.href);
  } catch {
    throw new Error("Enter a valid URL.");
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error("Only http and https URLs can be opened.");
  }
  const path = decodeURIComponent(url.pathname).toLowerCase();
  if (path.endsWith(".pmtiles")) return { kind: "pmtiles", href: url.href };
  if (path.endsWith(".mbtiles")) return { kind: "mbtiles", href: url.href };
  if (path.endsWith(".vtpk") || path.endsWith(".tpkx")) {
    return { kind: "vtpk", href: url.href };
  }
  if (path.endsWith(".json")) return { kind: "tilejson", href: url.href };
  return { kind: "unknown", href: url.href };
}

async function loadUnknown(
  href: string,
  token: number,
  signal: AbortSignal,
): Promise<LoadedSource> {
  try {
    const archive = new PMTiles(href);
    await archive.getHeader();
    return finishPmtiles(archive, nameFromUrl(href), token);
  } catch (error) {
    if (isAbort(error)) throw error;
  }
  try {
    const json = await downloadJson(href, signal);
    if (looksLikeTileJson(json) || looksLikeStyle(json)) {
      return finishTileJson(json, nameFromUrl(href), href, signal);
    }
  } catch (error) {
    if (isAbort(error)) throw error;
  }
  throw new Error(
    "Could not tell what this URL is. Use a .pmtiles, .mbtiles, .json, .vtpk, .tpkx link, or a template with {z}, {x}, and {y}.",
  );
}

async function finishPmtiles(
  archive: PMTiles,
  name: string,
  token: number,
): Promise<LoadedSource> {
  const key = holdPmtiles(archive, token);
  try {
    const header = await archive.getHeader();
    const metadata = await archive.getMetadata();
    const encoded =
      header.tileType === TileType.Mvt || header.tileType === TileType.Mlt;
    let vectorLayers = vectorLayersFromUnknown(metadata);
    let vector = encoded || vectorLayers.length > 0;
    if (header.tileType === TileType.Unknown && vectorLayers.length === 0) {
      vector = false;
    }
    if (vector && vectorLayers.length === 0 && header.tileType !== TileType.Mlt) {
      vectorLayers = await probePmtiles(archive, header);
    }
    if (vector && vectorLayers.length === 0) {
      throw new Error(
        header.tileType === TileType.Mlt
          ? "This MLT archive does not list its vector layers."
          : "No vector layers were found in this PMTiles archive.",
      );
    }
    const url = `pmtiles://${key}`;
    const source: TileSource = vector
      ? {
          type: "vector",
          url,
          ...(header.tileType === TileType.Mlt ? { encoding: "mlt" as const } : {}),
        }
      : { type: "raster", url };
    const metadataRecord = record(metadata);
    const metaName = metadataRecord?.name;
    return blank({
      name: typeof metaName === "string" && metaName ? metaName : name,
      format: "PMTiles",
      vector,
      bounds: lonLatBounds(header.minLon, header.minLat, header.maxLon, header.maxLat),
      center: [header.centerLon, header.centerLat],
      zoom: header.centerZoom,
      minzoom: header.minZoom,
      maxzoom: Math.max(header.minZoom, header.maxZoom),
      vectorLayers,
      attribution: attributionFrom(metadata),
      source,
      pmtilesKey: key,
    });
  } catch (error) {
    discardProtocolKeys(key, null, token);
    throw error;
  }
}

async function probePmtiles(archive: PMTiles, header: Header): Promise<string[]> {
  const z = header.minZoom;
  const lon = (header.minLon + header.maxLon) / 2;
  const lat = (header.minLat + header.maxLat) / 2;
  const nextZoom = Math.min(header.maxZoom, z + 1);
  const samples: [number, number, number][] = [
    [z, lonToTile(lon, z), latToTile(lat, z)],
    [z, lonToTile(lon, z) - 1, latToTile(lat, z)],
    [z, lonToTile(lon, z) + 1, latToTile(lat, z)],
    [nextZoom, lonToTile(lon, nextZoom), latToTile(lat, nextZoom)],
  ];
  const ids = new Set<string>();
  for (const [zz, x, y] of samples) {
    const limit = 2 ** zz;
    if (x < 0 || y < 0 || x >= limit || y >= limit) continue;
    const response = await archive.getZxy(zz, x, y);
    if (!response) continue;
    for (const id of await vectorLayerIds(new Uint8Array(response.data))) ids.add(id);
    if (ids.size) break;
  }
  return [...ids];
}

async function finishMbtiles(bytes: Uint8Array, name: string): Promise<LoadedSource> {
  const info = await openMbtilesBytes(bytes);
  const source: TileSource = info.session.vector
    ? {
        type: "vector",
        tiles: ["mbtiles://tiles/{z}/{x}/{y}"],
        minzoom: info.minzoom,
        maxzoom: info.maxzoom,
        attribution: info.attribution,
      }
    : {
        type: "raster",
        tiles: ["mbtiles://tiles/{z}/{x}/{y}"],
        tileSize: 256,
        minzoom: info.minzoom,
        maxzoom: info.maxzoom,
        attribution: info.attribution,
      };
  return blank({
    name,
    format: "MBTiles",
    vector: info.session.vector,
    bounds: info.bounds,
    minzoom: info.minzoom,
    maxzoom: info.maxzoom,
    vectorLayers: info.vectorLayers,
    attribution: info.attribution,
    source,
    mbtiles: info.session,
  });
}

async function finishPackage(
  archive: TilePackage,
  name: string,
  token: number,
): Promise<LoadedSource> {
  const key = holdPackage(archive, token);
  try {
    const header = await archive.getHeader();
    const style = asStyle(await archive.getStyle());
    const placed = centerFromStyle(style);
    const bounds =
      boundsFromExtent([
        header.minLon,
        header.minLat,
        header.maxLon,
        header.maxLat,
      ]) ?? boundsFromStyle(style);
    return blank({
      name: header.name || name,
      format: name.toLowerCase().endsWith(".tpkx") ? "TPKX" : "VTPK",
      vector: header.packageType !== "tpkx",
      bounds,
      center: placed.center,
      zoom: placed.zoom,
      minzoom: clampZoom(header.minZoom, 0),
      maxzoom: clampZoom(header.maxZoom, 22),
      vectorLayers: style.layers.map((layer) => layer.id),
      packageStyle: style,
      packageKey: key,
    });
  } catch (error) {
    discardProtocolKeys(null, key, token);
    throw error;
  }
}

async function finishTileJson(
  value: unknown,
  name: string,
  base: string | null,
  signal?: AbortSignal,
): Promise<LoadedSource> {
  if (looksLikeStyle(value) && !looksLikeTileJson(value)) {
    throw new Error(
      "This is a MapLibre style, not a TileJSON document. TileJSON needs a tiles array.",
    );
  }
  const root = record(value);
  if (!root || !Array.isArray(root.tiles) || root.tiles.length === 0) {
    throw new Error("TileJSON needs a tiles array.");
  }
  const templates = root.tiles.filter((tile): tile is string => typeof tile === "string");
  if (!templates.length) throw new Error("TileJSON tiles must be URL templates.");
  const tiles = resolveTiles(templates, base);
  const first = tiles[0] ?? "";
  const mlt = /\.mlt(\?|#|$)/i.test(first);
  let vectorLayers = vectorLayersFromUnknown(root);
  const hinted = templateKind(first);
  let vector = hinted === "vector" || vectorLayers.length > 0 || mlt;
  if (hinted === "raster") vector = false;
  let note: string | undefined;
  if (vector && vectorLayers.length === 0 && !mlt && signal) {
    const probed = await probeTemplate(first, signal);
    if (probed?.vector) vectorLayers = probed.layers;
    else if (probed && !probed.vector) vector = false;
  }
  if (vector && vectorLayers.length === 0) {
    throw new Error(
      mlt
        ? "This MLT TileJSON does not list vector_layers."
        : "No vector layers were found in this TileJSON.",
    );
  }
  const minzoom = clampZoom(root.minzoom, 0);
  const maxzoom = Math.max(minzoom, clampZoom(root.maxzoom, 22));
  const scheme = root.scheme === "tms" ? "tms" : "xyz";
  const attribution = attributionFrom(root);
  const bounds = boundsFromExtent(root.bounds);
  const tileSize = tileSizeFrom(root.tileSize);
  const source: TileSource = vector
    ? {
        type: "vector",
        tiles,
        minzoom,
        maxzoom,
        scheme,
        attribution,
        ...(mlt ? { encoding: "mlt" as const } : {}),
        ...(bounds ? { bounds } : {}),
      }
    : {
        type: "raster",
        tiles,
        tileSize,
        minzoom,
        maxzoom,
        scheme,
        attribution,
        ...(bounds ? { bounds } : {}),
      };
  const jsonName = root.name;
  return blank({
    name: typeof jsonName === "string" && jsonName ? jsonName : name,
    format: "TileJSON",
    vector,
    bounds,
    minzoom,
    maxzoom,
    vectorLayers,
    attribution,
    source,
    note,
  });
}

async function finishXyz(template: string, signal: AbortSignal): Promise<LoadedSource> {
  if (/\.mlt(\?|#|$)/i.test(template)) {
    throw new Error(
      "An MLT template needs a TileJSON or PMTiles archive that lists vector layers.",
    );
  }
  const hinted = templateKind(template);
  let vector = hinted === "vector";
  let vectorLayers: string[] = [];
  let note: string | undefined;
  if (vector || hinted === "unknown") {
    const probed = await probeTemplate(template, signal);
    if (probed?.vector) {
      vector = true;
      vectorLayers = probed.layers;
    } else if (probed && !probed.vector) {
      vector = false;
    } else if (hinted === "unknown") {
      vector = false;
      note = "Sample tiles did not identify the format, so this URL is shown as raster.";
    }
  }
  if (vector && vectorLayers.length === 0) {
    throw new Error("No vector layers were found in a sample tile.");
  }
  const attribution = attributionFor(template);
  const source: TileSource = vector
    ? { type: "vector", tiles: [template], minzoom: 0, maxzoom: 22, attribution }
    : {
        type: "raster",
        tiles: [template],
        tileSize: 256,
        minzoom: 0,
        maxzoom: 22,
        attribution,
      };
  return blank({
    name: nameFromUrl(template),
    format: "XYZ",
    vector,
    minzoom: 0,
    maxzoom: 22,
    vectorLayers,
    attribution,
    source,
    note,
  });
}

async function probeTemplate(
  template: string,
  signal: AbortSignal,
): Promise<{ vector: boolean; layers: string[] } | null> {
  const samples: [number, number, number][] = [
    [0, 0, 0],
    [1, 1, 1],
    [2, 2, 1],
    [3, 4, 2],
    [4, 8, 5],
    [5, 16, 10],
  ];
  let sawImage = false;
  for (const [z, x, y] of samples) {
    if (signal.aborted) throw new DOMException("Aborted", "AbortError");
    let response: Response;
    try {
      response = await fetch(expandTemplate(template, z, x, y), { signal });
    } catch (error) {
      if (isAbort(error)) throw error;
      continue;
    }
    if (!response.ok) continue;
    const bytes = new Uint8Array(await response.arrayBuffer());
    if (looksLikeImage(bytes)) {
      sawImage = true;
      continue;
    }
    const layers = await vectorLayerIds(bytes);
    if (layers.length) return { vector: true, layers };
  }
  return sawImage ? { vector: false, layers: [] } : null;
}

function expandTemplate(template: string, z: number, x: number, y: number): string {
  const flipped = 2 ** z - 1 - y;
  return template
    .replaceAll("{z}", String(z))
    .replaceAll("{x}", String(x))
    .replaceAll("{y}", String(y))
    .replaceAll("{-y}", String(flipped));
}

function templateKind(template: string): "vector" | "raster" | "unknown" {
  const path = template.split(/[?#]/)[0]?.toLowerCase() ?? "";
  if (/\.(pbf|mvt|mlt)$/.test(path)) return "vector";
  if (/\.(png|jpe?g|webp|gif|avif)$/.test(path)) return "raster";
  return "unknown";
}

function resolveTiles(tiles: string[], base: string | null): string[] {
  return tiles.map((tile) => {
    if (/^[a-z][a-z0-9+.-]*:\/\//i.test(tile)) return tile;
    if (!base) {
      throw new Error(
        "This TileJSON uses relative tile URLs. Open it from a URL so those paths can be resolved.",
      );
    }
    return new URL(tile, base).href;
  });
}

function blank(partial: {
  name: string;
  format: TileFormat;
  vector: boolean;
  bounds?: Bounds | null;
  center?: [number, number] | null;
  zoom?: number | null;
  minzoom: number;
  maxzoom: number;
  vectorLayers: string[];
  attribution?: string;
  source?: TileSource | null;
  packageStyle?: StyleSpecification | null;
  mbtiles?: MbtilesSession | null;
  pmtilesKey?: string | null;
  packageKey?: string | null;
  note?: string;
}): LoadedSource {
  const center = partial.center ?? null;
  const usableCenter =
    center && center.every((value) => Number.isFinite(value)) ? center : null;
  return {
    name: partial.name,
    format: partial.format,
    vector: partial.vector,
    bounds: partial.bounds ?? null,
    center: usableCenter,
    zoom: partial.zoom ?? null,
    minzoom: partial.minzoom,
    maxzoom: partial.maxzoom,
    vectorLayers: partial.vectorLayers,
    attribution: partial.attribution,
    source: partial.source ?? null,
    packageStyle: partial.packageStyle ?? null,
    mbtiles: partial.mbtiles ?? null,
    pmtilesKey: partial.pmtilesKey ?? null,
    packageKey: partial.packageKey ?? null,
    note: partial.note,
  };
}

function record(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function vectorLayersFromUnknown(value: unknown): string[] {
  const ids: string[] = [];
  const collect = (items: unknown) => {
    if (!Array.isArray(items)) return;
    for (const item of items) {
      const entry = record(item);
      if (!entry) continue;
      const id = entry.id ?? entry["source-layer"] ?? entry.name;
      if (typeof id === "string" && id && !ids.includes(id)) ids.push(id);
    }
  };
  const root = record(value);
  if (!root) return ids;
  collect(root.vector_layers);
  if (!ids.length) collect(root.layers);
  if (!ids.length && typeof root.json === "string") {
    try {
      const parsed = JSON.parse(root.json) as unknown;
      const inner = record(parsed);
      collect(inner?.vector_layers);
      if (!ids.length) collect(inner?.layers);
    } catch {
      // Optional metadata.
    }
  }
  return ids;
}

function attributionFrom(value: unknown): string | undefined {
  const root = record(value);
  return typeof root?.attribution === "string" && root.attribution
    ? root.attribution
    : undefined;
}

function looksLikeTileJson(value: unknown): boolean {
  const root = record(value);
  return !!root && Array.isArray(root.tiles);
}

function looksLikeStyle(value: unknown): boolean {
  const root = record(value);
  return !!root && root.version === 8 && Array.isArray(root.layers);
}

function asStyle(value: unknown): StyleSpecification {
  if (!looksLikeStyle(value)) {
    throw new Error("The package does not contain a MapLibre style.");
  }
  return value as StyleSpecification;
}

function centerFromStyle(style: StyleSpecification): {
  center: [number, number] | null;
  zoom: number | null;
} {
  const center = style.center;
  if (!center || center.length < 2) return { center: null, zoom: null };
  const lon = center[0];
  const lat = center[1];
  if (typeof lon !== "number" || typeof lat !== "number") {
    return { center: null, zoom: null };
  }
  return {
    center: [lon, lat],
    zoom: typeof style.zoom === "number" ? style.zoom : null,
  };
}

function boundsFromStyle(style: StyleSpecification): Bounds | null {
  const metadata = record(style.metadata);
  if (!metadata) return null;
  return boundsFromExtent(metadata["mapbox:bounds"] ?? metadata.bounds);
}

function tileSizeFrom(value: unknown): 256 | 512 {
  const number = typeof value === "number" ? value : Number(value);
  return number === 512 ? 512 : 256;
}

function parseJson(text: string): unknown {
  try {
    return JSON.parse(text) as unknown;
  } catch {
    throw new Error("This JSON file could not be parsed.");
  }
}

async function download(
  url: string,
  signal: AbortSignal,
  onSize?: (label: string) => void,
): Promise<Uint8Array> {
  const response = await fetch(url, { signal });
  if (!response.ok) {
    throw new Error(`Could not download the file (HTTP ${response.status}).`);
  }
  const length = Number(response.headers.get("content-length"));
  if (Number.isFinite(length) && length > 0) {
    onSize?.(`${(length / (1024 * 1024)).toFixed(1)} MB`);
  }
  return new Uint8Array(await response.arrayBuffer());
}

async function downloadJson(url: string, signal: AbortSignal): Promise<unknown> {
  const response = await fetch(url, { signal });
  if (!response.ok) {
    throw new Error(`Could not open the URL (HTTP ${response.status}).`);
  }
  return response.json() as Promise<unknown>;
}

function archiveUrl(input: string): string {
  const match = /^s3:\/\/([^/]+)\/(.+)$/i.exec(input);
  if (!match) return input;
  const bucket = match[1] ?? "";
  const key = match[2] ?? "";
  if (bucket.endsWith(".opendata.source.coop")) return `https://data.source.coop/${key}`;
  if (bucket.includes(".")) return `https://${bucket}/${key}`;
  throw new Error("This s3 URL has no https address the browser can open.");
}

function nameFromUrl(url: string): string {
  try {
    const parsed = new URL(url, window.location.href);
    const base = decodeURIComponent(parsed.pathname).split("/").filter(Boolean).pop();
    if (base && !base.includes("{")) return base;
    return parsed.host || url;
  } catch {
    return url;
  }
}

function attributionFor(template: string): string | undefined {
  if (template.includes("arcgisonline.com") || template.includes("arcgis.com")) {
    return "Esri";
  }
  return undefined;
}

function lonToTile(lon: number, zoom: number): number {
  return Math.floor(((lon + 180) / 360) * 2 ** zoom);
}

function latToTile(lat: number, zoom: number): number {
  const clamped = Math.max(-85.05112878, Math.min(85.05112878, lat));
  const radians = (clamped * Math.PI) / 180;
  const mercator = Math.log(Math.tan(radians) + 1 / Math.cos(radians));
  return Math.floor(((1 - mercator / Math.PI) / 2) * 2 ** zoom);
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}
