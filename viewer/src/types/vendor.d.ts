declare module "sql.js" {
  export type SqlValue = number | string | Uint8Array | null;

  export interface Statement {
    bind(values?: SqlValue[]): boolean;
    step(): boolean;
    getAsObject(): Record<string, SqlValue>;
    free(): boolean;
  }

  export interface QueryResult {
    columns: string[];
    values: SqlValue[][];
  }

  export interface Database {
    exec(sql: string): QueryResult[];
    prepare(sql: string): Statement;
    close(): void;
  }

  export interface SqlJsStatic {
    Database: new (data?: Uint8Array) => Database;
  }

  export default function initSqlJs(config?: {
    locateFile?: (file: string) => string;
  }): Promise<SqlJsStatic>;
}

declare module "maplibre-tilepackage-protocol" {
  import type { AddProtocolAction } from "maplibre-gl";

  export interface PackageHeader {
    name?: string;
    minLon?: number;
    minLat?: number;
    maxLon?: number;
    maxLat?: number;
    minZoom?: number;
    maxZoom?: number;
    packageType?: string;
    tileType?: string;
  }

  export class FileSource {
    constructor(file: File);
    getKey(): string;
  }

  export class TilePackage {
    source: { getKey(): string };
    constructor(source: FileSource | string);
    getHeader(): Promise<PackageHeader>;
    getStyle(): Promise<unknown>;
  }

  export class Protocol {
    tiles: Map<string, TilePackage>;
    package: AddProtocolAction;
    add(archive: TilePackage): void;
  }
}
