import argparse, sys, os
import gzip
from vtiles.pmtiles.writer import write
from vtiles.pmtiles.tile import TileType, zxy_to_tileid, tileid_to_zxy, Compression
import sqlite3
from tqdm import tqdm
import logging

from vtiles.utils.geopreocessing import check_vector, determine_tileformat
from vtiles.mbtiles.mbtilesfixmeta import fix_rastermetadata, fix_vectormetadata

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def mbtiles_to_header_json(mbtiles_metadata):
    header = {}

    header["min_zoom"] = int(mbtiles_metadata["minzoom"])

    header["max_zoom"] = int(mbtiles_metadata["maxzoom"])

    bounds = mbtiles_metadata["bounds"].split(",")
    header["min_lon_e7"] = int(float(bounds[0]) * 10000000)
    header["min_lat_e7"] = int(float(bounds[1]) * 10000000)
    header["max_lon_e7"] = int(float(bounds[2]) * 10000000)
    header["max_lat_e7"] = int(float(bounds[3]) * 10000000)

    center = mbtiles_metadata["center"].split(",")
    header["center_lon_e7"] = int(float(center[0]) * 10000000)
    header["center_lat_e7"] = int(float(center[1]) * 10000000)
    header["center_zoom"] = int(center[2])

    tile_format = mbtiles_metadata["format"]
    if tile_format == "pbf":
        header["tile_type"] = TileType.MVT
    elif tile_format == "png":
        header["tile_type"] = TileType.PNG
    elif tile_format == "jpeg":
        header["tile_type"] = TileType.JPEG
    elif tile_format == "webp":
        header["tile_type"] = TileType.WEBP
    elif tile_format == "avif":
        header["tile_type"] = TileType.AVIF
    else:
        header["tile_type"] = TileType.UNKNOWN

    if tile_format == "pbf" or mbtiles_metadata.get("compression") == "gzip":
        header["tile_compression"] = Compression.GZIP
    else:
        header["tile_compression"] = Compression.NONE

    return header, mbtiles_metadata

def mbtiles_to_pmtiles(input, output, verbose=True):
    try: 
        conn = sqlite3.connect(input)
        cursor = conn.cursor()
        with write(output) as writer:
            # collect a set of all tile IDs
            tileid_set = []
            # for row in cursor.execute(
            #     "SELECT zoom_level,tile_column,tile_row FROM tiles WHERE zoom_level <= ?",
            #     (maxzoom or 99,),
            # ):
            for row in cursor.execute(
                "SELECT zoom_level,tile_column,tile_row FROM tiles"
            ):
                flipped = (1 << row[0]) - 1 - row[2]
                tileid_set.append(zxy_to_tileid(row[0], row[1], flipped))

            tileid_set.sort()

            mbtiles_metadata = {}
            for row in cursor.execute("SELECT name,value FROM metadata"):
                mbtiles_metadata[row[0]] = row[1]
            is_pbf = mbtiles_metadata["format"] == "pbf"

            # query the db in ascending tile order
            for tileid in tqdm(tileid_set, desc="Converting tiles", disable=not verbose):
                z, x, y = tileid_to_zxy(tileid)
                flipped = (1 << z) - 1 - y
                res = cursor.execute(
                    "SELECT tile_data FROM tiles WHERE zoom_level = ? AND tile_column = ? AND tile_row = ?",
                    (z, x, flipped),
                )
                data = res.fetchone()[0]
                # force gzip compression only for vector
                if is_pbf and data[0:2] != b"\x1f\x8b":
                    data = gzip.compress(data)
                writer.write_tile(tileid, data)

            pmtiles_header, pmtiles_metadata = mbtiles_to_header_json(mbtiles_metadata)
            # if maxzoom:
            #     pmtiles_header["max_zoom"] = int(maxzoom)
            #     mbtiles_metadata["maxzoom"] = maxzoom
            writer.finalize(pmtiles_header, pmtiles_metadata)
        
        logging.info(f"Converting MBTiles to PMTile done!")
        cursor.close()
        conn.close()
    except sqlite3.Error as e:
        logging.error(f"Failed to read MBTiles file {input}: {e}")
    except Exception as e:
        logging.error(f"Failed to convert {input} to PMTiles: {e}")


def main():
    parser = argparse.ArgumentParser(description='Convert MBTiles to PMTiles.')
    parser.add_argument('input', help='Path to the input MBTiles file.')
    parser.add_argument('-o', '--output', help='Path to the output PMTiles file.')
    parser.add_argument('-v', '--verbose', action=argparse.BooleanOptionalAction, default=True, help='Show progress bar')
    
    args = parser.parse_args()
    if not os.path.exists(args.input):
        logging.error('Input MBTiles file does not exist! Please recheck and input a correct file path.')
        sys.exit(1)
        
    input_file_abspath = os.path.abspath(args.input)
    # Determine the output filename
    if args.output:
        output_file_abspath = os.path.abspath(args.output)
        if os.path.exists(output_file_abspath):
            logger.error(f'Output PMTiles  {output_file_abspath} already exists!. Please recheck and input a correct one. Ex: -o tiles.pmtiles')
            sys.exit(1)
        elif not output_file_abspath.endswith('pmtiles'):
            logger.error(f'Output PMTiles  {output_file_abspath} must end with .pmtiles. Please recheck and input a correct one. Ex: -o tiles.pmtiles')
            sys.exit(1)
    else:
        output_file_name = os.path.basename(input_file_abspath).replace('.mbtiles', '.pmtiles')
        output_file_abspath = os.path.join(os.path.dirname(input_file_abspath), output_file_name)
 
        if os.path.exists(output_file_abspath): 
            logger.error(f'Output PMTiles  {output_file_abspath} already exists! Please recheck and input a correct one. Ex: -o tiles.pmtiles')
            sys.exit(1)          

    is_vector, compression_type = check_vector(input_file_abspath) 
    tile_format = determine_tileformat(input_file_abspath)
    desc = 'Update metadata by vtiles.mbtiles.fixmeta' 
    if is_vector:
        fix_vectormetadata(input_file_abspath, compression_type,desc, args.verbose)   
    else:
        fix_rastermetadata(input_file_abspath, tile_format,desc)        

    logging.info(f'Converting {input_file_abspath} to {output_file_abspath}.')
    mbtiles_to_pmtiles(input_file_abspath, output_file_abspath, args.verbose)

if __name__ == "__main__":
    main()
