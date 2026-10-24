import type { StyleSpecification } from "@maplibre/maplibre-gl-style-spec";
import {
  FullscreenControl,
  GlobeControl,
  Map,
  NavigationControl,
  Popup,
  config,
  type IControl,
} from "maplibre-gl";
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import "maplibre-gl/dist/maplibre-gl.css";
import { adoptMbtiles } from "../lib/mbtiles";
import {
  adoptProtocolKeys,
  registerProtocols,
  releaseAllProtocols,
} from "../lib/protocols";
import {
  discardLoaded,
  loadFile,
  loadRemote,
  type LoadedSource,
} from "../lib/source";
import {
  BASEMAP_LAYER_PREFIX,
  buildViewerStyle,
  type LayerToggle,
} from "../lib/style";

const READY =
  "Open a PMTiles, MBTiles, TileJSON, {z}/{x}/{y}, or VTPK/TPKX.";

export function startViewer(): void {
  config.WORKER_URL = maplibreWorkerUrl;
  registerProtocols();

  const mapElement = required<HTMLDivElement>("map");
  const urlInput = required<HTMLInputElement>("url");
  const openButton = required<HTMLButtonElement>("open");
  const fileInput = required<HTMLInputElement>("file");
  const exampleSelect = required<HTMLSelectElement>("example");
  const fitButton = required<HTMLButtonElement>("fit");
  const clearButton = required<HTMLButtonElement>("clear");
  const backgroundInput = required<HTMLInputElement>("background");
  const tileBoundsInput = required<HTMLInputElement>("tile-bounds");
  const status = required<HTMLElement>("status");
  const summary = required<HTMLElement>("summary");
  const layerList = required<HTMLElement>("layers");
  const collapseButton = required<HTMLButtonElement>("collapse");
  const panel = required<HTMLElement>("panel");
  const drop = required<HTMLElement>("drop");

  const map = new Map({
    container: mapElement,
    style: buildViewerStyle(null, backgroundInput.checked).style,
    center: [0, 0],
    zoom: 1,
    maxZoom: 22,
    hash: false,
    attributionControl: { compact: false },
  });
  map.addControl(new FullscreenControl(), "top-right");
  map.addControl(new NavigationControl(), "top-right");
  map.addControl(new GlobeControl(), "top-right");
  map.addControl(new ZoomLevelControl(), "bottom-left");

  let generation = 0;
  let currentAbort: AbortController | null = null;
  let activePmtiles: string | null = null;
  let activePackage: string | null = null;
  let current: LoadedSource | null = null;
  let toggles: LayerToggle[] = [];

  const setStatus = (message: string, isError = false) => {
    status.textContent = message;
    status.classList.toggle("error", isError);
  };

  const renderPanel = () => {
    summary.replaceChildren();
    layerList.replaceChildren();
    if (!current) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "Open a tileset to list its layers.";
      layerList.append(empty);
      return;
    }
    const title = document.createElement("strong");
    title.textContent = current.name;
    title.title = current.name;
    const meta = document.createElement("p");
    const kind = current.vector ? "vector" : "raster";
    meta.textContent = `${current.format} · ${kind} · zoom ${current.minzoom}–${current.maxzoom}`;
    summary.append(title, meta);

    if (!toggles.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "This tileset has no listed layers.";
      layerList.append(empty);
      return;
    }

    for (const toggle of toggles) {
      const row = document.createElement("label");
      row.className = "layer";
      const box = document.createElement("input");
      box.type = "checkbox";
      box.checked = toggle.visible;
      box.addEventListener("change", () => {
        const visibility = box.checked ? "visible" : "none";
        for (const id of toggle.mapLayerIds) {
          if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", visibility);
        }
      });
      row.append(box);
      if (toggle.color) {
        const swatch = document.createElement("span");
        swatch.className = "swatch";
        swatch.style.background = toggle.color;
        row.append(swatch);
      }
      const text = document.createElement("span");
      text.className = "layer-name";
      text.textContent = toggle.label;
      text.title = toggle.label;
      row.append(text);
      if (toggle.detail) {
        const detail = document.createElement("span");
        detail.className = "layer-type";
        detail.textContent = toggle.detail;
        row.append(detail);
      }
      layerList.append(row);
    }
  };

  const replaceStyle = (style: StyleSpecification) =>
    new Promise<void>((resolve) => {
      const projection = map.getProjection();
      const next =
        projection?.type && projection.type !== "mercator"
          ? { ...style, projection }
          : style;
      map.once("style.load", () => resolve());
      map.setStyle(next, { diff: false });
    });

  const fitCurrent = () => {
    if (current?.bounds) {
      map.fitBounds(
        [
          [current.bounds[0], current.bounds[1]],
          [current.bounds[2], current.bounds[3]],
        ],
        { padding: 48, maxZoom: 16, duration: 650 },
      );
      return;
    }
    if (current?.center) {
      map.easeTo({
        center: current.center,
        zoom: current.zoom ?? map.getZoom(),
        duration: 650,
      });
      return;
    }
    map.fitBounds(
      [
        [-180, -85.0511],
        [180, 85.0511],
      ],
      { padding: 24, maxZoom: 2, duration: 650 },
    );
  };

  const rememberUrl = (url: string | null) => {
    const next = new URL(window.location.href);
    next.searchParams.delete("url");
    next.hash = url ? new URLSearchParams({ url }).toString() : "";
    history.replaceState(null, "", next);
  };

  const show = async (loaded: LoadedSource, token: number, shareUrl: string | null) => {
    if (token !== generation) {
      discardLoaded(loaded, token);
      return;
    }
    adoptMbtiles(loaded.mbtiles);
    adoptProtocolKeys(
      loaded.pmtilesKey,
      loaded.packageKey,
      activePmtiles,
      activePackage,
    );
    activePmtiles = loaded.pmtilesKey;
    activePackage = loaded.packageKey;
    current = loaded;
    const built = buildViewerStyle(loaded, backgroundInput.checked);
    toggles = built.toggles;
    renderPanel();
    await replaceStyle(built.style);
    if (token !== generation) return;
    map.showTileBoundaries = tileBoundsInput.checked;
    const canFit = loaded.bounds !== null || loaded.center !== null;
    fitButton.disabled = !canFit;
    clearButton.disabled = false;
    if (canFit) fitCurrent();
    const layers = loaded.vectorLayers.length
      ? ` · ${loaded.vectorLayers.length} ${loaded.packageStyle ? "style layers" : "layers"}`
      : "";
    const note = loaded.note ? ` ${loaded.note}` : "";
    setStatus(
      `${loaded.name} · ${loaded.format} · ${loaded.vector ? "vector" : "raster"} · zoom ${loaded.minzoom}–${loaded.maxzoom}${layers}.${note}`,
    );
    rememberUrl(shareUrl);
  };

  const begin = () => {
    currentAbort?.abort();
    currentAbort = new AbortController();
    generation += 1;
    return { token: generation, signal: currentAbort.signal };
  };

  const setBusy = (token: number, busy: boolean) => {
    if (token !== generation) return;
    openButton.disabled = busy;
    fileInput.disabled = busy;
  };

  const fail = (token: number, error: unknown) => {
    if (isAbort(error) || token !== generation) return;
    setStatus(error instanceof Error ? error.message : String(error), true);
  };

  const openLocal = async (file: File) => {
    const run = begin();
    setBusy(run.token, true);
    setStatus(`Opening ${file.name}…`);
    urlInput.value = "";
    try {
      const loaded = await loadFile(file, run.token);
      await show(loaded, run.token, null);
    } catch (error) {
      fail(run.token, error);
    } finally {
      setBusy(run.token, false);
      fileInput.value = "";
    }
  };

  const openAddress = async (address: string) => {
    const trimmed = address.trim();
    if (!trimmed) {
      setStatus("Enter a URL.", true);
      return;
    }
    const run = begin();
    setBusy(run.token, true);
    urlInput.value = trimmed;
    setStatus(`Opening ${trimmed}…`);
    try {
      const loaded = await loadRemote(trimmed, run.token, run.signal, setStatus);
      await show(loaded, run.token, trimmed);
    } catch (error) {
      fail(run.token, error);
    } finally {
      setBusy(run.token, false);
    }
  };

  openButton.addEventListener("click", () => {
    void openAddress(urlInput.value);
  });
  urlInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") void openAddress(urlInput.value);
  });
  fileInput.addEventListener("change", () => {
    const file = fileInput.files?.[0];
    if (file) void openLocal(file);
  });
  exampleSelect.addEventListener("change", () => {
    const value = exampleSelect.value;
    exampleSelect.value = "";
    if (value) void openAddress(value);
  });
  fitButton.addEventListener("click", fitCurrent);
  clearButton.addEventListener("click", () => {
    const run = begin();
    adoptMbtiles(null);
    releaseAllProtocols(activePmtiles, activePackage);
    activePmtiles = null;
    activePackage = null;
    current = null;
    toggles = [];
    renderPanel();
    fitButton.disabled = true;
    clearButton.disabled = true;
    openButton.disabled = false;
    fileInput.disabled = false;
    urlInput.value = "";
    rememberUrl(null);
    setStatus(READY);
    void replaceStyle(buildViewerStyle(null, backgroundInput.checked).style).then(() => {
      if (run.token === generation) map.showTileBoundaries = tileBoundsInput.checked;
    });
  });
  backgroundInput.addEventListener("change", () => {
    const visibility = backgroundInput.checked ? "visible" : "none";
    for (const layer of map.getStyle()?.layers ?? []) {
      if (!layer.id.startsWith(BASEMAP_LAYER_PREFIX) || !map.getLayer(layer.id)) continue;
      map.setLayoutProperty(layer.id, "visibility", visibility);
    }
  });
  tileBoundsInput.addEventListener("change", () => {
    map.showTileBoundaries = tileBoundsInput.checked;
  });
  collapseButton.addEventListener("click", () => {
    const collapsed = panel.classList.toggle("collapsed");
    collapseButton.textContent = collapsed ? "+" : "−";
    collapseButton.title = collapsed ? "Expand layers" : "Collapse layers";
    collapseButton.setAttribute("aria-expanded", collapsed ? "false" : "true");
  });

  map.on("click", (event) => {
    let features: ReturnType<Map["queryRenderedFeatures"]> = [];
    try {
      features = map.queryRenderedFeatures(event.point);
    } catch (error) {
      console.warn("Feature query failed.", error);
      return;
    }
    const feature = features.find((item) => {
      const id = item.layer.id;
      return !id.startsWith(BASEMAP_LAYER_PREFIX);
    });
    if (!feature) return;
    new Popup({ maxWidth: "320px", closeButton: true })
      .setLngLat(event.lngLat)
      .setDOMContent(featurePopup(feature))
      .addTo(map);
  });
  map.on("error", (event) => {
    const message = event.error?.message ?? "";
    if (/tile not found/i.test(message)) return;
    console.warn("Map error.", event.error);
  });

  let dragDepth = 0;
  window.addEventListener("dragenter", (event) => {
    if (!dragHasFiles(event)) return;
    event.preventDefault();
    dragDepth += 1;
    drop.hidden = false;
  });
  window.addEventListener("dragover", (event) => {
    if (!dragHasFiles(event)) return;
    event.preventDefault();
  });
  window.addEventListener("dragleave", () => {
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) drop.hidden = true;
  });
  window.addEventListener("drop", (event) => {
    if (!dragHasFiles(event)) return;
    event.preventDefault();
    dragDepth = 0;
    drop.hidden = true;
    const file = event.dataTransfer?.files[0];
    if (file) void openLocal(file);
  });

  renderPanel();
  setStatus(READY);

  const initial =
    new URL(window.location.href).searchParams.get("url") ??
    new URLSearchParams(window.location.hash.replace(/^#/, "")).get("url");
  if (initial) void openAddress(initial);
}

function featurePopup(feature: {
  sourceLayer?: string;
  layer: { id: string };
  geometry: { type: string };
  id?: string | number;
  properties?: Record<string, unknown> | null;
}): HTMLElement {
  const root = document.createElement("div");
  root.className = "popup-card";
  const title = document.createElement("div");
  title.className = "popup-title";
  title.textContent = feature.sourceLayer || feature.layer.id;
  const subtitle = document.createElement("div");
  subtitle.className = "popup-subtitle";
  subtitle.textContent = `${feature.geometry.type} · ${feature.id ?? "no id"}`;
  root.append(title, subtitle);
  const entries = Object.entries(feature.properties ?? {}).slice(0, 40);
  if (!entries.length) {
    const empty = document.createElement("div");
    empty.className = "popup-empty";
    empty.textContent = "No properties";
    root.append(empty);
    return root;
  }
  for (const [key, value] of entries) {
    const row = document.createElement("div");
    row.className = "popup-row";
    const name = document.createElement("span");
    name.className = "popup-key";
    name.textContent = key;
    const cell = document.createElement("span");
    cell.textContent = formatProperty(value);
    row.append(name, cell);
    root.append(row);
  }
  return root;
}

function formatProperty(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "object") {
    try {
      return JSON.stringify(value);
    } catch {
      return "";
    }
  }
  return String(value);
}

class ZoomLevelControl implements IControl {
  private map: Map | null = null;
  private label: HTMLElement | null = null;
  private readonly onZoom = () => {
    if (!this.map || !this.label) return;
    this.label.textContent = this.map.getZoom().toFixed(1);
  };

  onAdd(map: Map): HTMLElement {
    this.map = map;
    const container = document.createElement("div");
    container.className = "maplibregl-ctrl maplibregl-ctrl-group";
    const label = document.createElement("div");
    label.className = "viewer-zoom";
    label.title = "Zoom level";
    container.append(label);
    this.label = label;
    this.onZoom();
    map.on("zoom", this.onZoom);
    return container;
  }

  onRemove(): void {
    this.map?.off("zoom", this.onZoom);
    this.label?.parentElement?.remove();
    this.map = null;
    this.label = null;
  }
}

function required<T extends HTMLElement>(id: string): T {
  const element = document.getElementById(id);
  if (!element) throw new Error(`Missing #${id}`);
  return element as T;
}

function dragHasFiles(event: DragEvent): boolean {
  return [...(event.dataTransfer?.types ?? [])].includes("Files");
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}
