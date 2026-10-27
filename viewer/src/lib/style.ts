import type {
  LayerSpecification,
  StyleSpecification,
} from "@maplibre/maplibre-gl-style-spec";
import type { LoadedSource } from "./source";

export const BACKGROUND_STYLE_URL =
  "https://raw.githubusercontent.com/opengeoshub/vstyles/main/protomaps/viewer.json";
export const BASEMAP_LAYER_PREFIX = "viewer-basemap-";
const BASEMAP_SOURCE_ID = "viewer-basemap";
const PROTOMAPS_SOURCE_ID = "protomaps";
const TILESET_SOURCE_ID = "tileset";

const PALETTE = [
  "#e76f51",
  "#457b9d",
  "#2a9d8f",
  "#9b5de5",
  "#f4a261",
  "#d1495b",
  "#588157",
  "#4361ee",
  "#bc6c25",
  "#7b2cbf",
  "#0081a7",
  "#c44536",
  "#e9c46a",
  "#5e60ce",
  "#00b4d8",
];

export interface LayerToggle {
  id: string;
  label: string;
  detail?: string;
  color?: string;
  mapLayerIds: string[];
  visible: boolean;
}

export function buildViewerStyle(
  loaded: LoadedSource | null,
  background: StyleSpecification | null,
): { style: StyleSpecification; toggles: LayerToggle[] } {
  if (loaded?.packageStyle) {
    return packageStyle(loaded.packageStyle, background);
  }
  const basemap = basemapParts(background, true);
  const toggles: LayerToggle[] = [];
  const layers: LayerSpecification[] = [...basemap.layers];
  if (loaded?.source) {
    if (loaded.vector) {
      loaded.vectorLayers.forEach((name, index) => {
        const color = PALETTE[index % PALETTE.length] ?? "#888888";
        const key = safeId(name, index);
        const mapLayerIds = [
          `tileset-${key}-point`,
          `tileset-${key}-line`,
          `tileset-${key}-fill`,
          `tileset-${key}-outline`,
        ];
        toggles.push({
          id: name,
          label: name,
          color,
          mapLayerIds,
          visible: true,
        });
        layers.push(
          {
            id: mapLayerIds[2] ?? "",
            type: "fill",
            source: TILESET_SOURCE_ID,
            "source-layer": name,
            filter: ["==", ["geometry-type"], "Polygon"],
            paint: { "fill-color": color, "fill-opacity": 0.28 },
          },
          {
            id: mapLayerIds[3] ?? "",
            type: "line",
            source: TILESET_SOURCE_ID,
            "source-layer": name,
            filter: ["==", ["geometry-type"], "Polygon"],
            paint: { "line-color": color, "line-width": 1.1 },
          },
          {
            id: mapLayerIds[1] ?? "",
            type: "line",
            source: TILESET_SOURCE_ID,
            "source-layer": name,
            filter: ["==", ["geometry-type"], "LineString"],
            paint: { "line-color": color, "line-width": 1.5 },
          },
          {
            id: mapLayerIds[0] ?? "",
            type: "circle",
            source: TILESET_SOURCE_ID,
            "source-layer": name,
            filter: ["==", ["geometry-type"], "Point"],
            paint: {
              "circle-radius": 3.5,
              "circle-color": color,
              "circle-stroke-color": "#17191b",
              "circle-stroke-width": 0.8,
            },
          },
        );
      });
    } else {
      toggles.push({
        id: "raster",
        label: "Raster tiles",
        color: "#8d99ae",
        mapLayerIds: ["tileset-raster"],
        visible: true,
      });
      layers.push({
        id: "tileset-raster",
        type: "raster",
        source: TILESET_SOURCE_ID,
      });
    }
  }

  return {
    style: {
      version: 8,
      ...(basemap.sprite ? { sprite: basemap.sprite } : {}),
      ...(basemap.glyphs ? { glyphs: basemap.glyphs } : {}),
      sources: {
        ...basemap.sources,
        ...(loaded?.source ? { [TILESET_SOURCE_ID]: loaded.source } : {}),
      },
      layers,
    },
    toggles,
  };
}

function packageStyle(
  original: StyleSpecification,
  background: StyleSpecification | null,
): { style: StyleSpecification; toggles: LayerToggle[] } {
  const pkg = structuredClone(original);
  const packageLayers = (pkg.layers ?? []).filter(
    (layer) => !layer.id.startsWith(BASEMAP_LAYER_PREFIX),
  );
  const ownAssets = Boolean(pkg.glyphs || pkg.sprite);
  const basemap = basemapParts(background, !ownAssets);
  const packageSources = { ...(pkg.sources ?? {}) };
  delete packageSources[BASEMAP_SOURCE_ID];
  const toggles = packageLayers.map((layer) => ({
    id: layer.id,
    label: layer.id,
    detail: layer.type,
    mapLayerIds: [layer.id],
    visible: layerVisible(layer),
  }));
  const sprite = pkg.sprite ?? basemap.sprite;
  const glyphs = pkg.glyphs ?? basemap.glyphs;
  return {
    style: {
      version: 8,
      ...(pkg.name ? { name: pkg.name } : {}),
      ...(sprite ? { sprite } : {}),
      ...(glyphs ? { glyphs } : {}),
      sources: { ...basemap.sources, ...packageSources },
      layers: [...basemap.layers, ...packageLayers],
    },
    toggles,
  };
}

function basemapParts(
  background: StyleSpecification | null,
  symbols: boolean,
): {
  sources: StyleSpecification["sources"];
  layers: LayerSpecification[];
  sprite: StyleSpecification["sprite"];
  glyphs: StyleSpecification["glyphs"];
} {
  if (!background) {
    return { sources: {}, layers: [], sprite: undefined, glyphs: undefined };
  }
  const source = structuredClone(background.sources?.[PROTOMAPS_SOURCE_ID]);
  if (!source || source.type !== "vector" || !source.url?.startsWith("pmtiles://")) {
    throw new Error("Background style is missing a pmtiles:// source.");
  }
  const layers = (background.layers ?? [])
    .filter((layer) => symbols || layer.type !== "symbol")
    .map((layer) => {
      const next = structuredClone(layer);
      next.id = `${BASEMAP_LAYER_PREFIX}${layer.id}`;
      if ("source" in next && next.source === PROTOMAPS_SOURCE_ID) {
        next.source = BASEMAP_SOURCE_ID;
      }
      setVisibility(next, true);
      return next;
    });
  return {
    sources: { [BASEMAP_SOURCE_ID]: source },
    layers,
    sprite: background.sprite,
    glyphs: background.glyphs,
  };
}

function setVisibility(layer: LayerSpecification, visible: boolean): void {
  const visibility = visible ? "visible" : "none";
  if ("layout" in layer && layer.layout) {
    (layer.layout as { visibility?: "visible" | "none" }).visibility = visibility;
    return;
  }
  (layer as { layout: { visibility: "visible" | "none" } }).layout = { visibility };
}

function layerVisible(layer: LayerSpecification): boolean {
  if (!("layout" in layer) || !layer.layout) return true;
  return layer.layout.visibility !== "none";
}

function safeId(name: string, index: number): string {
  const cleaned = name.replace(/[^a-zA-Z0-9_-]/g, "-") || "layer";
  return `${cleaned}-${index}`;
}
