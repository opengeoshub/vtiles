export type Bounds = [number, number, number, number];

const MERCATOR_LIMIT = 20037508.342789244;

export function lonLatBounds(
  west: number,
  south: number,
  east: number,
  north: number,
): Bounds | null {
  if (![west, south, east, north].every(Number.isFinite)) return null;
  if (west < -180 || east > 180 || south < -90 || north > 90) return null;
  if (west > east || south > north) return null;
  if (west === east || south === north) return null;
  return [west, south, east, north];
}

function webMercatorToLonLat(x: number, y: number): [number, number] {
  const radius = 6378137;
  const lon = (x / radius) * (180 / Math.PI);
  const lat =
    (2 * Math.atan(Math.exp(y / radius)) - Math.PI / 2) * (180 / Math.PI);
  return [lon, lat];
}

function numbersFrom(value: unknown): [number, number, number, number] | null {
  if (typeof value === "string") {
    const parts = value.split(/[,\s]+/).map(Number);
    if (parts.length < 4 || parts.slice(0, 4).some((n) => !Number.isFinite(n))) {
      return null;
    }
    return [parts[0], parts[1], parts[2], parts[3]];
  }
  if (Array.isArray(value) && value.length >= 4) {
    const parts = value.slice(0, 4).map(Number);
    if (parts.some((n) => !Number.isFinite(n))) return null;
    return [parts[0], parts[1], parts[2], parts[3]];
  }
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    const west = record.west ?? record.xmin ?? record.minX;
    const south = record.south ?? record.ymin ?? record.minY;
    const east = record.east ?? record.xmax ?? record.maxX;
    const north = record.north ?? record.ymax ?? record.maxY;
    const parts = [west, south, east, north].map(Number);
    if (parts.some((n) => !Number.isFinite(n))) return null;
    return [parts[0], parts[1], parts[2], parts[3]];
  }
  return null;
}

/** Accepts longitude/latitude or Web Mercator metres. VTPK headers use either. */
export function boundsFromExtent(value: unknown): Bounds | null {
  const numbers = numbersFrom(value);
  if (!numbers) return null;
  const direct = lonLatBounds(numbers[0], numbers[1], numbers[2], numbers[3]);
  if (direct) return direct;

  const [xmin, ymin, xmax, ymax] = numbers;
  const mercator = [xmin, ymin, xmax, ymax].every(
    (n) => Math.abs(n) <= MERCATOR_LIMIT,
  );
  if (!mercator) return null;
  const southwest = webMercatorToLonLat(xmin, ymin);
  const northeast = webMercatorToLonLat(xmax, ymax);
  return lonLatBounds(
    southwest[0],
    southwest[1],
    northeast[0],
    northeast[1],
  );
}

export function clampZoom(value: unknown, fallback: number): number {
  const number = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.max(0, Math.min(24, Math.round(number)));
}
