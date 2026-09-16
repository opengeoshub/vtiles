import argparse, sys, os
import json
from .reader import Reader, MmapSource, all_tiles
from .tile import TileType
import sqlite3
from tqdm import tqdm
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def pmtiles_to_mbtiles(input, output, verbose=False):
    conn = sqlite3.connect(output)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE metadata (name text, value text);")
    cursor.execute("""create unique index name on metadata (name);""")
    cursor.execute(
        "CREATE TABLE tiles (zoom_level integer, tile_column integer, tile_row integer, tile_data blob);"
    )
    cursor.execute(
        "CREATE UNIQUE INDEX tile_index on tiles (zoom_level, tile_column, tile_row);"
    )

    with open(input, "r+b") as f:
        source = MmapSource(f)

        reader = Reader(source)
        header = reader.header()
        metadata = reader.metadata()

        # Set default metadata if not present
        metadata.setdefault("minzoom", header["min_zoom"])
        metadata.setdefault("maxzoom", header["max_zoom"])

        if "bounds" not in metadata:
            min_lon = header["min_lon_e7"] / 10000000
            min_lat = header["min_lat_e7"] / 10000000
            max_lon = header["max_lon_e7"] / 10000000
            max_lat = header["max_lat_e7"] / 10000000
            metadata["bounds"] = f"{min_lon},{min_lat},{max_lon},{max_lat}"

        if "center" not in metadata:
            center_lon = header["center_lon_e7"] / 10000000
            center_lat = header["center_lat_e7"] / 10000000
            center_zoom = header["center_zoom"]
            metadata["center"] = f"{center_lon},{center_lat},{center_zoom}"

        if "format" not in metadata and header["tile_type"] == TileType.MVT:
            metadata["format"] = "pbf"

        json_metadata = {}
        for k, v in metadata.items():
            if k in ["vector_layers", "tilestats"]:
                json_metadata[k] = v
                continue
            elif not isinstance(v, str):
                v = json.dumps(v, ensure_ascii=False)
            cursor.execute("INSERT INTO metadata VALUES(?,?)", (k, v))

        if json_metadata:
            cursor.execute(
                "INSERT INTO metadata VALUES(?,?)",
                ("json", json.dumps(json_metadata, ensure_ascii=False)),
            )

        tile_count = sum(1 for _ in all_tiles(source))
        for zxy, tile_data in tqdm(all_tiles(source), total=tile_count, desc="Converting tiles", disable=not verbose):
            flipped_y = (1 << zxy[0]) - 1 - zxy[2]
            cursor.execute(
                "INSERT INTO tiles VALUES(?,?,?,?)",
                (zxy[0], zxy[1], flipped_y, tile_data),
            )

    conn.commit()
    conn.close()

def main():
    parser = argparse.ArgumentParser(description='Convert PMTiles to MBTiles.')
    parser.add_argument('input', help='Path to the input PMTiles file.')
    parser.add_argument('-o', '--output', help='Path to the output MBTiles file.')
    parser.add_argument('-v', '--verbose', action='store_true', help='Show progress bar')
    
    args = parser.parse_args()
    if not os.path.exists(args.input):
        logging.error('Input PMTiles file does not exist! Please recheck and input a correct file path.')
        sys.exit(1)
        
    input_file_abspath = os.path.abspath(args.input)
    # Determine the output filename
    if args.output:
        output_file_abspath = os.path.abspath(args.output)
        if os.path.exists(output_file_abspath):
            logger.error(f'Output MBTIles  {output_file_abspath} already exists!. Please recheck and input a correct one. Ex: -o tiles.mbtiles')
            sys.exit(1)
        elif not output_file_abspath.endswith('mbtiles'):
            logger.error(f'Output MBTIles  {output_file_abspath} must end with .mbtiles. Please recheck and input a correct one. Ex: -o tiles.mbtiles')
            sys.exit(1)
    else:
        output_file_name = os.path.basename(input_file_abspath).replace('.pmtiles', '.mbtiles')
        output_file_abspath = os.path.join(os.path.dirname(input_file_abspath), output_file_name)
 
        if os.path.exists(output_file_abspath): 
            logger.error(f'Output MBTiles  {output_file_abspath} already exists! Please recheck and input a correct one. Ex: -o tiles.mbtiles')
            sys.exit(1)          

    logging.info(f'Converting {input_file_abspath} to {output_file_abspath}.')
    pmtiles_to_mbtiles(input_file_abspath, output_file_abspath, args.verbose)
    logging.info(f'Converting PMTiles to MBTiles done!')

if __name__ == "__main__":
    main()
