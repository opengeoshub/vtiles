#!/usr/bin/env python
import os,sys, logging
import sqlite3
import json
import argparse
from tqdm import tqdm
from vtiles.utils.geopreocessing import flip_y, safe_makedir,determine_tileformat

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

def extract_metadata(mbtiles):
    """Extract metadata from MBTiles file."""
    try:
        conn = sqlite3.connect(mbtiles)
        cursor = conn.cursor()
        cursor.execute("SELECT name, value FROM metadata")
        metadata_rows = cursor.fetchall()
        metadata = {name: value for name, value in metadata_rows}
        return metadata
    except sqlite3.Error as e:
        logging.warning(f"Error reading metadata: {e}")
        return None
    finally:
        cursor.close()
        conn.close()

def write_metadata_to_json(metadata, dirname):
    """Write metadata to JSON file."""
    metadata_json_path = os.path.join(dirname, "metadata.json")
    with open(metadata_json_path, "w") as metadata_file:
        json.dump(metadata, metadata_file, indent=4)
    logging.info("Writing metadata.json done!")

def get_max_zoom(mbtiles):
    try:
        conn = sqlite3.connect(mbtiles)
        cursor = conn.cursor()
        cursor.execute('SELECT MAX(zoom_level) FROM tiles')
        return cursor.fetchone()[0]
    finally:
        cursor.close()
        conn.close()

def convert_mbtiles_to_folder(mbtiles, output_folder, flipy, min_zoom=0, max_zoom=None, verbose=True):
    conn = sqlite3.connect(mbtiles)
    cursor = conn.cursor()
    
    tile_format = determine_tileformat(mbtiles)
    
    mbtiles_max_zoom = get_max_zoom(mbtiles)
    max_zoom = max_zoom if max_zoom is not None and max_zoom <= mbtiles_max_zoom else mbtiles_max_zoom

    metadata = extract_metadata(mbtiles)
    if metadata:
        write_metadata_to_json(metadata, output_folder)
    
    cursor.execute('SELECT zoom_level, tile_column, tile_row, tile_data FROM tiles WHERE zoom_level BETWEEN ? AND ? ORDER BY zoom_level', (min_zoom, max_zoom))
    tiles = cursor.fetchall()

    for zoom, col, row, tile_data in tqdm(tiles, unit=' tiles ', desc='Processing tiles', disable=not verbose):
        # Flip the Y coordinate if flipy is True
        y = flip_y(zoom, row) if flipy else row

        # Construct the directory path
        tile_dir = os.path.join(output_folder, str(zoom), str(col))
        safe_makedir(tile_dir)

        # Construct the file path
        tile_path = os.path.join(tile_dir, f'{y}.{tile_format}')

        # Write the tile data to the file
        try:
            with open(tile_path, 'wb') as tile_file:
                tile_file.write(tile_data)
        except Exception as e:
            print(f"Error writing tile at {tile_path}: {e}")

    logging.info('Converting MBTiles to folder done!')
    
    cursor.close()
    conn.close()

def main():
    parser = argparse.ArgumentParser(description='Convert MBTiles file to tiles folder')
    parser.add_argument('input', help='Input MBTiles file name')
    parser.add_argument('-o', '--output',help='Output folder name (optional)')
    parser.add_argument('-flipy', type=int, default=0, choices=[0, 1], help='TMS <--> XYZ tiling scheme (optional): 1 or 0, default is 0')
    parser.add_argument('-minzoom', type=int, default=0, help='Min zoom to export (optional, default is 0)')
    parser.add_argument('-maxzoom', type=int, default=None, help='Max zoom to export (optional, default is the maxzoom of the input MBTiles)')
    parser.add_argument('-v', '--verbose', action=argparse.BooleanOptionalAction, default=True, help='Show progress bar')

    args = parser.parse_args()

    if not os.path.exists(args.input):
        logging.error('MBTiles file does not exist! Please recheck and input a correct file path.')
        sys.exit(1)
    
    input_filename_abspath = os.path.abspath(args.input)
    # Determine the output folder
    if args.output:
        output_folder_abspath = os.path.abspath(args.output)
    else:
        output_folder_abspath = os.path.join(os.path.dirname(args.input), os.path.splitext(os.path.basename(args.input))[0])

    # Create output folder if it doesn't exist
    if not os.path.exists(output_folder_abspath):
        os.makedirs(output_folder_abspath)
    else:         
        logging.error(f'Output folder {output_folder_abspath} already existed. Please provide a valid folder with -o.')
        sys.exit(1)

    # Inform the user of the conversion
    logging.info(f'Converting {input_filename_abspath} to {output_folder_abspath} folder.')
    convert_mbtiles_to_folder(input_filename_abspath, output_folder_abspath, args.flipy, args.minzoom, args.maxzoom, args.verbose)

if __name__ == "__main__":
    main()
