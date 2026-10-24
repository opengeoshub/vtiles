import { addProtocol, type AddProtocolAction } from "maplibre-gl";
import {
  FileSource as PackageFile,
  Protocol as PackageProtocol,
  TilePackage,
} from "maplibre-tilepackage-protocol";
import { FileSource, PMTiles, Protocol } from "pmtiles";
import { serveMbtilesTile } from "./mbtiles";

export const pmtilesProtocol = new Protocol({ metadata: true });
export const packageProtocol = new PackageProtocol();

const pmtilesOwners = new Map<string, number>();
const packageOwners = new Map<string, number>();

let registered = false;

export function registerProtocols(): void {
  if (registered) return;
  addProtocol("pmtiles", pmtilesProtocol.tile as AddProtocolAction);
  addProtocol("tilepackage", packageProtocol.package);
  addProtocol("mbtiles", serveMbtilesTile);
  registered = true;
}

export function holdPmtiles(archive: PMTiles, token: number): string {
  const key = archive.source.getKey();
  pmtilesProtocol.add(archive);
  pmtilesOwners.set(key, token);
  return key;
}

export function holdPackage(archive: TilePackage, token: number): string {
  const key = archive.source.getKey();
  packageProtocol.add(archive);
  packageOwners.set(key, token);
  return key;
}

export function adoptProtocolKeys(
  pmtilesKey: string | null,
  packageKey: string | null,
  previousPmtiles: string | null,
  previousPackage: string | null,
): void {
  if (previousPmtiles && previousPmtiles !== pmtilesKey) {
    pmtilesProtocol.tiles.delete(previousPmtiles);
    pmtilesOwners.delete(previousPmtiles);
  }
  if (previousPackage && previousPackage !== packageKey) {
    packageProtocol.tiles.delete(previousPackage);
    packageOwners.delete(previousPackage);
  }
  if (pmtilesKey) pmtilesOwners.set(pmtilesKey, 0);
  if (packageKey) packageOwners.set(packageKey, 0);
}

export function discardProtocolKeys(
  pmtilesKey: string | null,
  packageKey: string | null,
  token: number,
): void {
  if (pmtilesKey && pmtilesOwners.get(pmtilesKey) === token) {
    pmtilesProtocol.tiles.delete(pmtilesKey);
    pmtilesOwners.delete(pmtilesKey);
  }
  if (packageKey && packageOwners.get(packageKey) === token) {
    packageProtocol.tiles.delete(packageKey);
    packageOwners.delete(packageKey);
  }
}

export function releaseAllProtocols(
  pmtilesKey: string | null,
  packageKey: string | null,
): void {
  if (pmtilesKey) {
    pmtilesProtocol.tiles.delete(pmtilesKey);
    pmtilesOwners.delete(pmtilesKey);
  }
  if (packageKey) {
    packageProtocol.tiles.delete(packageKey);
    packageOwners.delete(packageKey);
  }
}

export function pmtilesFromFile(file: File): PMTiles {
  return new PMTiles(new FileSource(file));
}

export function packageFromFile(file: File): TilePackage {
  return new TilePackage(new PackageFile(file));
}
