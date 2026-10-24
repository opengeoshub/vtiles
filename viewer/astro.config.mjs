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

export default defineConfig({
  vite: {
    plugins: [scopeSqlJsModule()],
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
