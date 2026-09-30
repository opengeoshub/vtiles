import sqlite3
import os, sys, argparse, textwrap
from vtiles.utils.geopreocessing import check_vector, determine_tileformat,\
                                        count_tiles, count_tiles_for_each_zoom,\
                                        get_zoom_levels,get_bounds_center,find_duplicates,\
                                        get_standard_tile_count, decode_tile_data
from concurrent.futures import ProcessPoolExecutor, as_completed
import logging
from tqdm import tqdm

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def inspect_mbtiles(mbtiles, verbose=True):
    is_vector, compression_type = check_vector(mbtiles) 
    tile_format = determine_tileformat(mbtiles)
    min_zoom, max_zoom = get_zoom_levels(mbtiles)
    tile_count = count_tiles(mbtiles)
    bounds, center = get_bounds_center(mbtiles)
    print(f"Min zoom level: {min_zoom}")
    print(f"Max zoom level: {max_zoom}")
    print(f"Total number of tiles: {tile_count}")
    print(f"Bounds: {bounds}")
    print(f"Center: {center}")
    print(f"Tile format: {tile_format}")
    print(f"Compression type: {compression_type}")

    print("\nTile counts for each zoom level:")
    tile_count_zoom = count_tiles_for_each_zoom(mbtiles)
    # Print results with standard number of tiles
    print(f"{'Zoom Level':<12} {'Actual Tile Count':<20} {'Standard Tile Count':<20} {'Matches Standard'}")
    print("="*62)
    for zoom_level, actual_tile_count in tile_count_zoom:
        standard_tile_count = get_standard_tile_count(zoom_level)
        matches_standard = "Yes" if actual_tile_count == standard_tile_count else "No"
        print(f"{zoom_level:<12} {actual_tile_count:<20} {standard_tile_count:<20} {matches_standard}")
    
        duplicates, total_duplicates= find_duplicates(mbtiles)
    
    # Print duplicates
    print(f"\nTotal number of duplicate rows: {total_duplicates}")
    rows_limit = 10
    if total_duplicates > 0:
        # Header for the duplicates table
        print(f"{'Zoom Level':<12} {'Tile Column':<12} {'Tile Row':<12} {'Duplicates':<6}")
        print("=" * 42)
        
        # Print only the first 10 duplicates
        for zoom_level, tile_column, tile_row, count in duplicates[:rows_limit]:
            print(f"{zoom_level:<12} {tile_column:<12} {tile_row:<12} {count:<6}")

        # Inform the user how many duplicates are in total
        if total_duplicates > rows_limit:
            print(f"\n...and {total_duplicates - rows_limit} more duplicates")
        
        print("\nNote: Please consider to use mbtilesdelduplicate to delete duplicates!")

    if is_vector:
        print("\nListing layers at each zoom level:")
        batch_size=10000
        workers=4
        list_layers_for_all_zoom_levels_parallel(mbtiles,batch_size,workers,verbose)


# Function to process a batch of tiles and extract unique layers
def process_tile_batch(tile_batch):
    layers = set()
    for tile_column, tile_row, tile_data in tile_batch:
        # Decode the vector tile using mapbox_vector_tile
        decoded_tile = decode_tile_data(tile_data)
        # Add all the layer names to the set
        layers.update(decoded_tile.keys())
    
    return layers

# Function to process all zoom levels in parallel and accumulate results
def list_layers_for_all_zoom_levels_parallel(mbtiles_file, batch_size=10000, workers=4, verbose=True):
    # Connect to the MBTiles file (SQLite database)
    conn = sqlite3.connect(mbtiles_file)
    cursor = conn.cursor()

    # Query distinct zoom levels from the tiles table
    cursor.execute("SELECT DISTINCT zoom_level FROM tiles ORDER BY zoom_level")
    zoom_levels = cursor.fetchall()

    # Dictionary to accumulate results for each zoom level
    results = {}

    # Iterate through each zoom level
    for zoom_level_tuple in zoom_levels:
        zoom_level = zoom_level_tuple[0]

        # Query the tiles for the current zoom level
        cursor.execute("SELECT tile_column, tile_row, tile_data FROM tiles WHERE zoom_level = ?", (zoom_level,))
        tiles = cursor.fetchall()

        # Split tiles into batches of `batch_size`
        batches = [tiles[i:i + batch_size] for i in range(0, len(tiles), batch_size)]

        # Initialize a set to hold unique layers for this zoom level
        layers = set()

        # Use ProcessPoolExecutor for parallel processing
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(process_tile_batch, batch): batch for batch in batches}

            # Use tqdm for progress tracking
            for future in tqdm(as_completed(futures), total=len(batches), desc=f"Processing Zoom {zoom_level}", disable=not verbose):
                # Add the layers from the processed batch to the main set
                layers.update(future.result())

        # Store the sorted layer list for this zoom level
        results[zoom_level] = sorted(layers)

    # Close the database connection
    cursor.close()
    conn.close()

    max_width = 80
    print(f"{'Zoom Level':<12} {'Layers'}")
    print("=" * 92)
    for zoom_level, layer_list in results.items():
        layer_string = ", ".join(layer_list)
        wrapped_layers = textwrap.wrap(layer_string, width=max_width) or [""]
        print(f"{zoom_level:<12} {wrapped_layers[0]}")
        for continuation in wrapped_layers[1:]:
            print(f"{'':<12} {continuation}")

def main():
    parser = argparse.ArgumentParser(description='Inspect MBTiles file with analyzing tile_data in tiles table.')
    parser.add_argument('input', help='Path to the MBTiles file.')
    parser.add_argument('-v', '--verbose', action=argparse.BooleanOptionalAction, default=True, help='Show progress bar')

    args = parser.parse_args()
    mbtiles = args.input

    if (os.path.exists(mbtiles)):
       inspect_mbtiles(mbtiles, args.verbose)       
    else: 
        logger.error ('MBTiles file does not exist!. Please recheck and input a correct file path.')
        sys.exit(1)

if __name__ == '__main__':
    main()