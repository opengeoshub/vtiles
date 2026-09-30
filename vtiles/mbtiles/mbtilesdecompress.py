import argparse, sys, os
import sqlite3
import zlib
import gzip
import logging
import shutil
from tqdm import tqdm
from vtiles.utils.geopreocessing import check_vector

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def decompress_tile_data(tile_data):
    try:
        if tile_data[:2] == b'\x1f\x8b':  # Check for gzip magic number
            tile_data = gzip.decompress(tile_data)
        elif tile_data[:2] == b'\x78\x9c' or tile_data[:2] == b'\x78\x01' or tile_data[:2] == b'\x78\xda':
            tile_data = zlib.decompress(tile_data) 
    except Exception as e:
        logging.error(f"Failed to decompress tile data: {e}")
        return tile_data
    return tile_data          

def decompress_mbtiles(input_mbtiles, output_mbtiles, batch_size=10000, verbose=True):
    shutil.copyfile(input_mbtiles, output_mbtiles)
    
    # Open the copied MBTiles file
    conn = sqlite3.connect(output_mbtiles)
    cursor = conn.cursor()

    # Check if the tiles table is a view
    cursor.execute("SELECT type FROM sqlite_master WHERE name='tiles'")
    result = cursor.fetchone()

    def process_tiles(tiles):
        batch = []
        for zoom_level, tile_column, tile_row, tile_data in tiles:
            try:
                decompressed_tile = decompress_tile_data(tile_data)
                batch.append((decompressed_tile, zoom_level, tile_column, tile_row))
            except Exception as e:
                logging.error(f"Error decompressing tile {zoom_level}/{tile_column}/{tile_row}: {e}")
            
            # Commit batch once it reaches the batch_size
            if len(batch) >= batch_size:
                cursor.executemany(
                    "UPDATE tiles SET tile_data = ? WHERE zoom_level = ? AND tile_column = ? AND tile_row = ?",
                    batch
                )
                conn.commit()  # Commit the batch
                batch.clear()  # Clear batch

        # Commit any remaining tiles in the batch
        if batch:
            cursor.executemany(
                "UPDATE tiles SET tile_data = ? WHERE zoom_level = ? AND tile_column = ? AND tile_row = ?",
                batch
            )
            conn.commit()

    if result and result[0] == 'view':
        # Create a new table named tiles_new
        cursor.execute("CREATE TABLE tiles_new (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)")
        
        # Select data from the view
        cursor.execute("SELECT zoom_level, tile_column, tile_row, tile_data FROM tiles ORDER BY zoom_level")
        tiles = cursor.fetchall()
        
        batch = []
        for zoom_level, tile_column, tile_row, tile_data in tqdm(tiles, desc="Decompressing tiles", unit="tile", disable=not verbose):
            try:
                decompressed_tile = decompress_tile_data(tile_data)
                batch.append((zoom_level, tile_column, tile_row, decompressed_tile))
            except Exception as e:
                logging.error(f"Error decompressing tile {zoom_level}/{tile_column}/{tile_row}: {e}")
            
            # Insert decompressed data in batches
            if len(batch) >= batch_size:
                cursor.executemany(
                    "INSERT INTO tiles_new (zoom_level, tile_column, tile_row, tile_data) VALUES (?, ?, ?, ?)",
                    batch
                )
                conn.commit()  # Commit batch
                batch.clear()  # Clear batch

        # Commit remaining tiles in the batch
        if batch:
            cursor.executemany(
                "INSERT INTO tiles_new (zoom_level, tile_column, tile_row, tile_data) VALUES (?, ?, ?, ?)",
                batch
            )
            conn.commit()

        # Drop the view and rename the new table to tiles
        cursor.execute("DROP VIEW tiles")
        cursor.execute("ALTER TABLE tiles_new RENAME TO tiles")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS tile_index ON tiles (zoom_level, tile_column, tile_row)")

    else:
        # Decompress tile data in the existing tiles table
        cursor.execute("SELECT zoom_level, tile_column, tile_row, tile_data FROM tiles ORDER BY zoom_level")
        tiles = cursor.fetchall()
        
        # Process the tiles in batches
        process_tiles(tqdm(tiles, desc="Decompressing tiles", unit="tile", disable=not verbose))

    # Commit and close connections
    conn.commit()
    conn.close()


def main():
    parser = argparse.ArgumentParser(description='Decompress an MBTiles file.')
    parser.add_argument('input', help='Path to the input MBTiles file.')
    parser.add_argument('-o', '--output', help='Path to the output MBTiles file.')
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
            logger.error(f'Output MBTiles file {output_file_abspath} already exists!. Please recheck and input a correct one. Ex: -o tiles.mbtiles')
            sys.exit(1)
        elif not output_file_abspath.endswith('mbtiles'):
            logger.error(f'Output MBTiles file {output_file_abspath} must end with .mbtiles. Please recheck and input a correct one. Ex: -o tiles.mbtiles')
            sys.exit(1)
    else:
        output_file_name = os.path.basename(input_file_abspath).replace('.mbtiles', '_decompressed.mbtiles')
        output_file_abspath = os.path.join(os.path.dirname(input_file_abspath), output_file_name)
 
        if os.path.exists(output_file_abspath): 
            logger.error(f'Output MBTiles file {output_file_abspath} already exists! Please recheck and input a correct one. Ex: -o tiles.mbtiles')
            sys.exit(1)          

    # Inform the user of the conversion
    is_vector, _ = check_vector(args.input)
    if is_vector:
        logging.info(f'Decompressing {input_file_abspath} to {output_file_abspath}.') 
        decompress_mbtiles(input_file_abspath, output_file_abspath, verbose=args.verbose)
    else:
        logging.warning(f'mbtilesdecompress only supports vector MBTiles. {input_file_abspath} is not a vector MBTiles.')
        sys.exit(1)


if __name__ == "__main__":
    main()
