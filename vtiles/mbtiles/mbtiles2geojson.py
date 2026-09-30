import json
import argparse
import sqlite3
import argparse, sys, os
from vtiles.utils.vt2geojson.tools import vt_bytes_to_geojson
import gzip
import zlib
import logging
from tqdm import tqdm
from vtiles.utils.geopreocessing import check_vector

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def tile_data_to_geojson(tile_data, x, y, z, layers):   
    try:
        features = vt_bytes_to_geojson(tile_data, x, y, z)
        if layers:
            filtered_features = {layer: features[layer] for layer in layers if layer in features}
        else:
            filtered_features = features

        # Add zoom level to each feature's properties
        for layer, feature_collection in filtered_features.items():
            for feature in feature_collection['features']:
                if 'properties' not in feature:
                    feature['properties'] = {}
                feature['properties']['zoom_level'] = z
        
        return filtered_features
    except Exception as e:
        logging.error(f"Error converting tile data to GeoJSON at tile ({x}, {y}, {z}): {e}")
        return None

def decompress_tile_data(tile_data):  
    try:
        if tile_data[:2] == b'\x1f\x8b':  # Check for gzip magic number
            return gzip.decompress(tile_data)
        elif tile_data[:2] in {b'\x78\x9c', b'\x78\x01', b'\x78\xda'}:
            return zlib.decompress(tile_data)
        return tile_data
    except Exception as e:
        logging.error(f"Failed to decompress tile data: {e}")
        return tile_data
    
def merge_geojsons(geojson_list):
    merged_geojson = {}

    for geojson in geojson_list:
        for key, feature_collection in geojson.items():
            if key not in merged_geojson:
                merged_geojson[key] = {'type': 'FeatureCollection', 'features': []}
            merged_geojson[key]['features'].extend(feature_collection['features'])
    
    return merged_geojson

def mbtiles_to_geojson(input_mbtiles, output_geojson, compression_type, zoom_level, flip_y, layers, chunk_size=1000, verbose=True):
    """
    Convert MBTiles data to GeoJSON format in chunks.

    Args:
        input_mbtiles (str): Path to the input MBTiles file.
        output_geojson (str): Path to the output GeoJSON file.
        compression_type (str): Compression type (GZIP or ZLIB).
        zoom_level (int): The zoom level of tiles to extract.
        flip_y (bool): Whether to flip the y coordinate (TMS format).
        layers (list): List of layer names to include in the output.
        chunk_size (int): Number of rows to process per chunk (default: 1000).
    """
    all_features = []

    try:
        conn = sqlite3.connect(input_mbtiles)
        cursor = conn.cursor()

        offset = 0
        more_tiles = True

        while more_tiles:
            # Fetch a chunk of tile data
            cursor.execute(f'''
                SELECT tile_column, tile_row, tile_data 
                FROM tiles 
                WHERE zoom_level=? 
                LIMIT ? OFFSET ?''', (zoom_level, chunk_size, offset))
            rows = cursor.fetchall()

            if not rows:
                more_tiles = False  # No more tiles to fetch

            for x, y, tile_data in tqdm(rows, desc=f"Converting tiles at zoom level {zoom_level} to GeoJSON", disable=not verbose):
                if tile_data:
                    if flip_y:
                        y = (1 << zoom_level) - 1 - y

                    if compression_type == 'GZIP' or compression_type == 'ZLIB':
                        tile_data = decompress_tile_data(tile_data)

                    features = tile_data_to_geojson(tile_data, x, y, zoom_level, layers)
                    if features:
                        all_features.append(features)

            offset += chunk_size  # Move to the next chunk

        # Close the cursor and connection
        cursor.close()
        conn.close()

        # Merge and save the resulting GeoJSON
        merged_geojson = merge_geojsons(all_features)
        with open(output_geojson, 'w') as f:
            json.dump(merged_geojson, f, indent=2)

        logging.info(f"GeoJSON data has been saved to {output_geojson}")

    except sqlite3.Error as e:
        logging.error(f"Failed to read MBTiles file {input_mbtiles}: {e}")
    except Exception as e:
        logging.error(f"Failed to convert {input_mbtiles} to GeoJSON: {e}")

def main():
    """
    Main function to parse arguments and convert MBTiles to GeoJSON.
    """
    parser = argparse.ArgumentParser(description='Convert MBTiles to GeoJSON.')  
    parser.add_argument('input', help='Input MBTiles file')
    parser.add_argument('-o', '--output', help='Output GeoJSON file')
    parser.add_argument('-z','--zoom', type=int, required=True, help='Minimum tile zoom level')
    parser.add_argument('-flipy', '--flipy', type=int, choices=[0, 1], default=0, help='TMS <--> XYZ tiling scheme (optional): 1 or 0, default is 0')
    parser.add_argument('-l', '--layers', type=str, nargs='*', help='List of layer names to convert')
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
            logger.error(f'Output GeoJSON file {output_file_abspath} alreday exists!. Please recheck and input a correct one. Ex: -o tiles.geojson')
            sys.exit(1)
        elif not output_file_abspath.endswith('geojson'):
            logger.error(f'Output GeoJSON file {output_file_abspath} must end with .geojson. Please recheck and input a correct one. Ex: -o tiles.geojson')
            sys.exit(1)
    else:
        output_file_name = os.path.basename(input_file_abspath).replace('.mbtiles', '_z' + str(args.zoom) + '.geojson')
        output_file_abspath = os.path.join(os.path.dirname(input_file_abspath), output_file_name)
 
        if os.path.exists(output_file_abspath): 
            logger.error(f'Output GeoJSON file {output_file_abspath} already exists! Please recheck and input a correct one. Ex: -o tiles.geojson')
            sys.exit(1)          

    # Inform the user of the conversion
    is_vector, compression_type = check_vector(args.input)
    if is_vector:
        logging.info(f'Converting {input_file_abspath} to {output_file_abspath}.') 
        mbtiles_to_geojson(input_file_abspath, output_file_abspath,compression_type, args.zoom, args.flipy, args.layers, verbose=args.verbose)
    else:
        logging.warning(f'mbtiles2gojson only supports vector MBTiles. {input_file_abspath} is not a vector MBTiles.')
        sys.exit(1)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
