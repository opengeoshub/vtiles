// @ts-check
import { defineConfig } from "astro/config";

/** Keep Emscripten's `module` assignment local so the prebundled sql.js module stays valid ESM. */
function scopeSqlJsModule() {
  return {
    name: "scope-sqljs-module",
    /** @param {string} code @param {string} id */
    transform(code, id) {
      const normalized = id.split("\\").join("/");
      if (!normalized.includes("sql.js/dist/sql-wasm")) return null;
      return code.replace("module = undefined;", "var module = undefined;");
    },
  };
}

const protomapsBasemapProxy = {
  "/basemap/protomaps.pmtiles": {
    target: "https://latest.protomaps.com",
    changeOrigin: true,
    rewrite: () => "/v4.pmtiles",
  },
};

export default defineConfig({
  vite: {
    plugins: [scopeSqlJsModule()],
    server: { proxy: protomapsBasemapProxy },
    preview: { proxy: protomapsBasemapProxy },
    optimizeDeps: {
      include: [
        "sql.js",
        "maplibre-gl",
        "pmtiles",
        "@mapbox/vector-tile",
        "pbf",
        "maplibre-tilepackage-protocol",
      ],
    },
    worker: {
      format: "es",
    },
  },
});
