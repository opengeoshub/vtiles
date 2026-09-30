import argparse
import gzip
import json
import logging
import math
import os
import sys
from collections import defaultdict
from datetime import date, datetime
from numbers import Number

from shapely.geometry import Polygon

from vtiles.pmtiles.tile import Compression, TileType, zxy_to_tileid
from vtiles.pmtiles.writer import write
from vtiles.utils.mapbox_vector_tile import encode
import vtiles.utils.mercantile as mercantile

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

H3_COLUMN_NAMES = ("h3", "h3_index", "h3_id", "hex_id", "hexagon")
LAT_LIMIT = 85.05112878


def import_h3():
    try:
        import h3
    except ImportError:
        logger.error("h3 is required to convert H3 Parquet files. Install it with: pip install h3")
        sys.exit(1)
    return h3


def import_pyarrow_parquet():
    try:
        import pyarrow.parquet as pq
    except ImportError:
        logger.error("pyarrow is required to read Parquet files. Install it with: pip install pyarrow")
        sys.exit(1)
    return pq


def read_parquet_table(input_path):
    pq = import_pyarrow_parquet()
    try:
        return pq.read_table(input_path)
    except Exception as e:
        logger.error(f"Failed to read Parquet file {input_path}: {e}")
        sys.exit(1)


def detect_h3_column(table, requested=None):
    names = list(table.schema.names)
    if requested:
        if requested not in names:
            logger.error(f"H3 column '{requested}' was not found in the Parquet file.")
            sys.exit(1)
        return requested

    lowered = {name.lower(): name for name in names}
    for candidate in H3_COLUMN_NAMES:
        if candidate in lowered:
            return lowered[candidate]

    logger.error(
        "No H3 column found. Expected a column named h3 (or h3_index / h3_id). "
        "Pass the column name with --h3."
    )
    sys.exit(1)


def sanitize_value(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value > 2**63 - 1 or value < -(2**63):
            return str(value)
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (list, dict, tuple)):
        try:
            return json.dumps(value, default=str, ensure_ascii=False)
        except TypeError:
            return str(value)
    if hasattr(value, "as_py"):
        return sanitize_value(value.as_py())
    if hasattr(value, "item"):
        try:
            return sanitize_value(value.item())
        except Exception:
            pass
    return str(value)


def sanitize_properties(row):
    properties = {}
    for key, value in row.items():
        cleaned = sanitize_value(value)
        if cleaned is not None:
            properties[str(key)] = cleaned
    return properties


def feature_id(row, index):
    value = row.get("id", index)
    if isinstance(value, bool) or not isinstance(value, Number) or value < 0:
        return index
    return int(value)


def infer_fields(features):
    fields = {}
    for feature in features:
        for key, value in feature.get("properties", {}).items():
            if key not in fields:
                fields[key] = type(value).__name__
    return fields


def normalize_h3_cell(value, h3):
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, int):
        try:
            value = h3.int_to_str(value)
        except Exception:
            value = format(value, "x")
    cell = str(value).strip()
    if not cell:
        return None
    if not h3.is_valid_cell(cell):
        return None
    return cell


def shift_antimeridian_ring(coords):
    """Same rule as vgrid/pop (h3FixTransmeridianBoundary): if any vertex is
    west of -130°, shift every positive longitude by -360° so the ring stays
    contiguous around -180 instead of wrapping the long way across the map.
    """
    if any(lon < -130 for lon, _lat in coords):
        return [(lon - 360 if lon > 0 else lon, lat) for lon, lat in coords]
    return coords


def h3_polygon(cell, h3):
    boundary = h3.cell_to_boundary(cell)
    coords = [(lng, lat) for lat, lng in boundary]
    if len(coords) < 3:
        return None
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    polygon = Polygon(shift_antimeridian_ring(coords))
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    if polygon is None or polygon.is_empty:
        return None
    return polygon


def wrapping_bboxes(polygon):
    minx, miny, maxx, maxy = polygon.bounds
    south = max(-LAT_LIMIT, min(LAT_LIMIT, miny))
    north = max(-LAT_LIMIT, min(LAT_LIMIT, maxy))
    if south > north:
        south, north = north, south
    bboxes = []
    west = max(-180.0, minx)
    east = min(180.0, maxx)
    if west < east:
        bboxes.append((west, south, east, north))
    if minx < -180:
        bboxes.append((max(-180.0, minx + 360), south, 180.0, north))
    if maxx > 180:
        bboxes.append((-180.0, south, min(180.0, maxx - 360), north))
    return bboxes


def centroid_tiles(cell, h3, minzoom, maxzoom):
    """Assign each H3 cell to the single XYZ tile that contains its centroid."""
    lat, lng = h3.cell_to_latlng(cell)
    lat = max(-LAT_LIMIT, min(LAT_LIMIT, lat))
    if lng < -180:
        lng += 360
    elif lng >= 180:
        lng -= 360
    return [mercantile.tile(lng, lat, z, truncate=True) for z in range(minzoom, maxzoom + 1)]


def clip_bounds(bounds):
    min_lon, min_lat, max_lon, max_lat = bounds
    min_lon = max(-180.0, min(180.0, min_lon))
    max_lon = max(-180.0, min(180.0, max_lon))
    min_lat = max(-LAT_LIMIT, min(LAT_LIMIT, min_lat))
    max_lat = max(-LAT_LIMIT, min(LAT_LIMIT, max_lat))
    if min_lon == max_lon:
        min_lon = max(-180.0, min_lon - 0.0001)
        max_lon = min(180.0, max_lon + 0.0001)
    if min_lat == max_lat:
        min_lat = max(-LAT_LIMIT, min_lat - 0.0001)
        max_lat = min(LAT_LIMIT, max_lat + 0.0001)
    return min_lon, min_lat, max_lon, max_lat


def expand_bounds(bounds, polygon):
    for west, south, east, north in wrapping_bboxes(polygon):
        if bounds is None:
            bounds = (west, south, east, north)
        else:
            bounds = (
                min(bounds[0], west),
                min(bounds[1], south),
                max(bounds[2], east),
                max(bounds[3], north),
            )
    return bounds


def build_pmtiles_header(bounds, minzoom, maxzoom):
    min_lon, min_lat, max_lon, max_lat = clip_bounds(bounds)
    return {
        "tile_type": TileType.MVT,
        "tile_compression": Compression.GZIP,
        "min_zoom": int(minzoom),
        "max_zoom": int(maxzoom),
        "min_lon_e7": int(min_lon * 10000000),
        "min_lat_e7": int(min_lat * 10000000),
        "max_lon_e7": int(max_lon * 10000000),
        "max_lat_e7": int(max_lat * 10000000),
        "center_zoom": int(minzoom),
        "center_lon_e7": int(((min_lon + max_lon) / 2) * 10000000),
        "center_lat_e7": int(((min_lat + max_lat) / 2) * 10000000),
    }


def build_pmtiles_metadata(name, layer_name, fields, bounds, minzoom, maxzoom):
    min_lon, min_lat, max_lon, max_lat = clip_bounds(bounds)
    return {
        "name": name,
        "description": "Converted from H3 Parquet by vtiles.pmtiles.h3parquet2pmtiles",
        "format": "pbf",
        "type": "overlay",
        "geometry": "none",
        "minzoom": int(minzoom),
        "maxzoom": int(maxzoom),
        "bounds": f"{min_lon},{min_lat},{max_lon},{max_lat}",
        "center": f"{(min_lon + max_lon) / 2},{(min_lat + max_lat) / 2},{minzoom}",
        "vector_layers": [{
            "id": layer_name,
            "minzoom": int(minzoom),
            "maxzoom": int(maxzoom),
            "fields": fields,
            "geometry": "none",
        }],
    }


def resolve_output_path(input_path, output):
    if output:
        output_path = os.path.abspath(output)
        if os.path.exists(output_path):
            logger.error(
                f"Output PMTiles {output_path} already exists!. Please recheck and input a correct one. Ex: -o tiles.pmtiles"
            )
            sys.exit(1)
        if not output_path.endswith("pmtiles"):
            logger.error(
                f"Output PMTiles {output_path} must end with .pmtiles. Please recheck and input a correct one. Ex: -o tiles.pmtiles"
            )
            sys.exit(1)
        return output_path

    base = os.path.basename(input_path.rstrip("\\/"))
    for suffix in (".parquet", ".pq", ".geoparquet"):
        if base.lower().endswith(suffix):
            base = base[: -len(suffix)]
            break
    output_path = os.path.join(os.path.dirname(os.path.abspath(input_path)), f"{base}.pmtiles")
    if os.path.exists(output_path):
        logger.error(
            f"Output PMTiles {output_path} already exists! Please recheck and input a correct one. Ex: -o tiles.pmtiles"
        )
        sys.exit(1)
    return output_path


def iter_progress(items, desc, verbose):
    if not verbose:
        return items
    try:
        from tqdm import tqdm
        return tqdm(items, desc=desc, unit=" rows" if "H3" in desc else " tiles")
    except ImportError:
        return items


def assign_features_to_tiles(rows, h3_column, minzoom, maxzoom, verbose=True):
    h3 = import_h3()
    tiles_features = defaultdict(list)
    bounds = None
    skipped = 0
    placed = 0

    for index, row in enumerate(iter_progress(rows, "Matching H3 cells to tiles", verbose)):
        cell = normalize_h3_cell(row.get(h3_column), h3)
        if cell is None:
            skipped += 1
            continue
        polygon = h3_polygon(cell, h3)
        if polygon is None:
            skipped += 1
            continue

        bounds = expand_bounds(bounds, polygon)
        properties = sanitize_properties(row)
        properties[str(h3_column)] = cell
        properties["h3"] = cell
        feature = {
            "id": feature_id(row, index),
            "geometry": None,
            "properties": properties,
        }
        matched = centroid_tiles(cell, h3, minzoom, maxzoom)
        if not matched:
            skipped += 1
            continue
        placed += 1
        for tile in matched:
            tiles_features[(tile.z, tile.x, tile.y)].append(feature)

    return tiles_features, bounds, placed, skipped


def write_attribute_tiles(output_path, tiles_features, layer_name, name, bounds, minzoom, maxzoom, verbose=True):
    sample_features = next(iter(tiles_features.values()))
    metadata = build_pmtiles_metadata(
        name, layer_name, infer_fields(sample_features), bounds, minzoom, maxzoom
    )

    encoded_tiles = []
    items = sorted(tiles_features.items(), key=lambda item: zxy_to_tileid(*item[0]))
    for (z, x, y), features in iter_progress(items, "Encoding tiles", verbose):
        encoded = encode(
            [{"name": layer_name, "features": features}],
            default_options={"allow_null_geometry": True},
        )
        encoded_tiles.append((zxy_to_tileid(z, x, y), gzip.compress(encoded)))

    with write(output_path) as writer:
        for tileid, tile_data in encoded_tiles:
            writer.write_tile(tileid, tile_data)
        writer.finalize(build_pmtiles_header(bounds, minzoom, maxzoom), metadata)

    logger.info(f"Wrote {len(encoded_tiles)} attribute-only tiles.")


def h3parquet_to_pmtiles(
    input_path,
    output_path,
    maxzoom=5,
    minzoom=0,
    h3_column=None,
    layer_name=None,
    verbose=True,
):
    table = read_parquet_table(input_path)
    if table.num_rows == 0:
        logger.error("Parquet file contains no rows.")
        sys.exit(1)

    h3_column = detect_h3_column(table, h3_column)
    layer_name = layer_name or os.path.splitext(os.path.basename(input_path.rstrip("\\/")))[0]
    name = os.path.basename(output_path)
    logger.info(f"Using H3 column '{h3_column}' (centroid-within tiles). Geometry will not be stored.")

    tiles_features, bounds, placed, skipped = assign_features_to_tiles(
        table.to_pylist(), h3_column, minzoom, maxzoom, verbose
    )
    if skipped:
        logger.warning(f"Skipped {skipped} rows without a valid H3 cell or tile match.")
    if not tiles_features:
        logger.error("No H3 cells could be matched to tiles.")
        sys.exit(1)

    logger.info(f"Matched {placed} H3 cells to {len(tiles_features)} tiles.")
    write_attribute_tiles(
        output_path, tiles_features, layer_name, name, bounds, minzoom, maxzoom, verbose
    )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Convert an H3 Parquet file to PMTiles. Each H3 cell is assigned to the "
            "XYZ tile that contains its centroid; the output stores attributes without geometry."
        )
    )
    parser.add_argument("input", help="Input Parquet file with an H3 cell column.")
    parser.add_argument("-o", "--output", help="Output PMTiles file.")
    parser.add_argument("-z", "--maxzoom", type=int, default=5, help="Maximum zoom level (default: 5).")
    parser.add_argument("--minzoom", type=int, default=0, help="Minimum zoom level (default: 0).")
    parser.add_argument("--h3", dest="h3_column", help="H3 cell column name (default: auto-detect h3).")
    parser.add_argument("--layer", help="Vector tile layer name (default: input file name).")
    parser.add_argument("-v", "--verbose", action=argparse.BooleanOptionalAction, default=True, help="Show progress.")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        logger.error("Input Parquet file does not exist! Please recheck and input a correct file path.")
        sys.exit(1)
    if args.maxzoom < 0 or args.maxzoom > 24:
        logger.error("maxzoom must be between 0 and 24.")
        sys.exit(1)
    if args.minzoom < 0 or args.minzoom > args.maxzoom:
        logger.error("minzoom must be between 0 and maxzoom.")
        sys.exit(1)

    input_path = os.path.abspath(args.input)
    output_path = resolve_output_path(input_path, args.output)
    logger.info(f"Converting {input_path} to {output_path}.")
    h3parquet_to_pmtiles(
        input_path,
        output_path,
        maxzoom=args.maxzoom,
        minzoom=args.minzoom,
        h3_column=args.h3_column,
        layer_name=args.layer,
        verbose=args.verbose,
    )
    logger.info("Converting H3 Parquet to PMTiles done!")


if __name__ == "__main__":
    main()
