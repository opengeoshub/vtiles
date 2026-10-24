import { VectorTile } from "@mapbox/vector-tile";
import { PbfReader } from "pbf";

export async function decompressTile(bytes: Uint8Array): Promise<Uint8Array> {
  const format = compressionFormat(bytes);
  if (!format) return bytes;
  if (typeof DecompressionStream === "undefined") {
    throw new Error("This browser cannot decompress MBTiles tiles.");
  }
  const stream = new Blob([toArrayBuffer(bytes)])
    .stream()
    .pipeThrough(new DecompressionStream(format));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

export async function gunzipIfNeeded(bytes: Uint8Array): Promise<Uint8Array> {
  return decompressTile(bytes);
}

function compressionFormat(bytes: Uint8Array): "gzip" | "deflate" | null {
  if (bytes.length < 2) return null;
  if (bytes[0] === 0x1f && bytes[1] === 0x8b) return "gzip";
  if (bytes[0] === 0x78) return "deflate";
  return null;
}

export function looksLikeImage(bytes: Uint8Array): boolean {
  if (bytes.length < 3) return false;
  if (bytes[0] === 0x89 && bytes[1] === 0x50 && bytes[2] === 0x4e) return true;
  if (bytes[0] === 0xff && bytes[1] === 0xd8) return true;
  if (
    bytes.length >= 4 &&
    bytes[0] === 0x52 &&
    bytes[1] === 0x49 &&
    bytes[2] === 0x46 &&
    bytes[3] === 0x46
  ) {
    return true;
  }
  if (bytes[0] === 0x47 && bytes[1] === 0x49 && bytes[2] === 0x46) return true;
  return false;
}

export async function vectorLayerIds(bytes: Uint8Array): Promise<string[]> {
  try {
    const raw = await gunzipIfNeeded(bytes);
    const tile = new VectorTile(new PbfReader(raw));
    return Object.keys(tile.layers);
  } catch {
    return [];
  }
}

export function toArrayBuffer(bytes: Uint8Array): ArrayBuffer {
  const copy = new ArrayBuffer(bytes.byteLength);
  new Uint8Array(copy).set(bytes);
  return copy;
}

export function asBytes(value: unknown): Uint8Array | null {
  if (value instanceof Uint8Array) return value;
  if (value instanceof ArrayBuffer) return new Uint8Array(value);
  if (ArrayBuffer.isView(value)) {
    return new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
  }
  return null;
}
