import sqlite3
import shutil
import gzip, zlib
import json
import argparse, sys, os
from tqdm import tqdm
from vtiles.utils.mapbox_vector_tile import encode, decode
from vtiles.utils.geopreocessing import fix_wkt
import logging
from vtiles.mbtiles.mbtilesfixmeta import fix_vectormetadata
from vtiles.utils.geopreocessing import check_vector

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def process_metadata(metadata_json, layers_to_keep, exclude=False):
    vector_layers = metadata_json.get('vector_layers', [])
    if exclude:
        processed_layers = [layer for layer in vector_layers if layer['id'] not in layers_to_keep]
    else:
        processed_layers = [layer for layer in vector_layers if layer['id'] in layers_to_keep]
    
    tilestats = metadata_json.get('tilestats', {})
    updated_stats = tilestats.copy()
    updated_stats['layerCount'] = len(processed_layers)
    updated_stats['layers'] = [
                            stat for stat in updated_stats.get('layers', [])
                            if (exclude and stat['layer'] not in layers_to_keep) or (not exclude and stat['layer'] in layers_to_keep)
                            ]

    metadata_json['vector_layers'] = processed_layers
    metadata_json['tilestats'] = updated_stats
    
    return metadata_json


def process_mbtiles(input_mbtiles, output_mbtiles, layers_to_keep, keep_layers=True, verbose=True):
    is_vector, compression_type = check_vector(input_mbtiles) 
    desc = 'Update metadata by vtiles.mbtiles.mbtilesfixmeta' 
    if is_vector:
        fix_vectormetadata(input_mbtiles, compression_type,desc, verbose)    
        shutil.copyfile(input_mbtiles, output_mbtiles)    
        with sqlite3.connect(output_mbtiles) as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT name, value FROM metadata WHERE name = 'json'")
            metadata = cursor.fetchone()
            
            if metadata:
                _, metadata_value = metadata
                metadata_json = json.loads(metadata_value)
                processed_metadata = process_metadata(metadata_json, layers_to_keep, exclude=not keep_layers)
                cursor.execute("DELETE FROM metadata WHERE name = 'json'")
                cursor.execute("INSERT INTO metadata (name, value) VALUES ('json', ?)", (json.dumps(processed_metadata),))
            
            cursor.execute("SELECT type FROM sqlite_master WHERE name='tiles'")
            result = cursor.fetchone()
            if result:
                if result[0] == 'view':
                    cursor.execute("DROP VIEW IF EXISTS tiles")
                else:
                    cursor.execute("DROP TABLE IF EXISTS tiles")
            
            cursor.execute("""
                CREATE TABLE tiles (
                    zoom_level INTEGER,
                    tile_column INTEGER,
                    tile_row INTEGER,
                    tile_data BLOB
                )
            """)
            cursor.execute("CREATE UNIQUE INDEX tile_index ON tiles (zoom_level, tile_column, tile_row)")
            
            try:
                with sqlite3.connect(input_mbtiles) as in_conn:
                    in_cursor = in_conn.cursor()
                    in_cursor.execute("SELECT zoom_level, tile_column, tile_row, tile_data FROM tiles ORDER BY zoom_level")
                    tiles = in_cursor.fetchall()
                    
                    for zoom_level, tile_column, tile_row, tile_data in tqdm(tiles, desc="Processing tiles", unit=" tiles", disable=not verbose):
                        if tile_data[:2] == b'\x1f\x8b':
                            tile_data = gzip.decompress(tile_data)
                        elif tile_data[:2] in [b'\x78\x9c', b'\x78\x01', b'\x78\xda']:
                            tile_data = zlib.decompress(tile_data)
                        
                        decoded_tile = decode(tile_data)
                        decoded_tile = fix_wkt(decoded_tile)
                        
                        if keep_layers:
                            filtered_tile = [item for item in decoded_tile if item["name"] in layers_to_keep]
                        else:
                            filtered_tile = [item for item in decoded_tile if item["name"] not in layers_to_keep]
                        
                        if filtered_tile:
                            try:
                                encoded_tile = encode(filtered_tile)
                                encoded_tile_gzip = gzip.compress(encoded_tile)
                                cursor.execute("""
                                    INSERT OR REPLACE INTO tiles (zoom_level, tile_column, tile_row, tile_data)
                                    VALUES (?, ?, ?, ?)""", (zoom_level, tile_column, tile_row, encoded_tile_gzip))
                            except Exception as e:
                                logger.error(f"Error encoding tile {zoom_level}/{tile_column}/{tile_row}: {e}")
                
                description = 'Splitting MBTiles file by selected layers using mbtilessplit from vtiles'
                cursor.execute('''
                    INSERT OR REPLACE INTO metadata (name, value)
                    VALUES ('description', ?)
                ''', (description,))
                
                conn.commit()
                if keep_layers:
                    logger.info(f'Successfully saved split MBTiles into {output_mbtiles}')
                else:
                    logger.info(f'Successfully saved remaining MBTiles into {output_mbtiles}')
            
            except sqlite3.Error as e:
                logger.error(f"Database error: {e}")
            except Exception as e:
                logger.error(f"Unexpected error: {e}")


def main():
    parser = argparse.ArgumentParser(description="Split an MBTiles file by selected layers.")
    parser.add_argument('input', help='Path to the input MBTiles file.')
    parser.add_argument('-o', '--output', help='Path to the output splitted MBTiles file.')
    parser.add_argument("-l", "--layers", nargs='+', required=True, help="List of layer names to be splitted")
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
            logger.error(f'Output MBTiles  {output_file_abspath} already exists!. Please recheck and input a correct one. Ex: -o tiles.mbtiles')
            sys.exit(1)
        elif not output_file_abspath.endswith('mbtiles'):
            logger.error(f'Output MBTiles  {output_file_abspath} must end with .mbtiles. Please recheck and input a correct one. Ex: -o tiles.mbtiles')
            sys.exit(1)
    else:
        output_file_name = os.path.basename(input_file_abspath).replace('.mbtiles', '_splitted.mbtiles')
        output_file_abspath = os.path.join(os.path.dirname(input_file_abspath), output_file_name)
 
        if os.path.exists(output_file_abspath): 
            logger.error(f'Output MBTiles  {output_file_abspath} already exists! Please recheck and input a correct one. Ex: -o tiles.mbtiles')
            sys.exit(1)          
    
    remaining_output = os.path.join(
        os.path.dirname(output_file_abspath),
        os.path.basename(input_file_abspath).replace('.mbtiles', '_remained.mbtiles')
    )
    if os.path.exists(remaining_output):
        logger.error(f'Output MBTiles  {remaining_output} already exists!. Please recheck and input a correct one.')
        sys.exit(1)

    logger.info(f'Splitting {input_file_abspath} to {output_file_abspath}')
    process_mbtiles(input_file_abspath, output_file_abspath, args.layers, keep_layers=True, verbose=args.verbose)
    process_mbtiles(input_file_abspath, remaining_output, args.layers, keep_layers=False, verbose=args.verbose)
    logger.info('Splitting MBTiles done!')

if __name__ == "__main__":
    main()