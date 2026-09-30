# Reference: 
# https://github.com/mapbox/mbtiles-spec/blob/master/1.3/spec.md
# https://github.com/mapbox/tippecanoe/blob/master/main.cpp#L2033

import os, sys, argparse, sqlite3, json
from vtiles.utils.geopreocessing import check_vector, determine_tileformat,\
                                         get_zoom_levels,get_bounds_center, decode_tile_data
from concurrent.futures import ProcessPoolExecutor, as_completed
from tqdm import tqdm
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def extract_layer_fields(layer_data):
    """Extract field types from layer data."""
    fields = {}
    for feature in layer_data['features']:
        for key, value in feature['properties'].items():
            if key not in fields:  # Only add if not already present
                fields[key] = type(value).__name__  # Store the type of each field
    return fields

def decode_tile_batch(tile_batch, zoom_level):
    """Decode a batch of tiles and extract layer information."""
    layers = {}
    
    for tile_data_tuple in tile_batch:
        tile_data = tile_data_tuple[0]  # Extract tile data from the tuple
        decoded_tile = decode_tile_data(tile_data)
        if decoded_tile:  # Ensure decoded_tile is valid
            for layer_name, layer_data in decoded_tile.items():
                if layer_name not in layers:
                    # Initialize minzoom and maxzoom
                    layers[layer_name] = {
                        "fields": extract_layer_fields(layer_data),
                        "minzoom": zoom_level,
                        "maxzoom": zoom_level,
                    }
                else:
                    # Update maxzoom for the layer if it appears in a new zoom level
                    layers[layer_name]["maxzoom"] = max(layers[layer_name]["maxzoom"], zoom_level)

    return layers  

def merge_layer_dicts(layers_accumulated, new_layers):
    """Merge two dictionaries of layers."""
    for name, layer in new_layers.items():
        if name not in layers_accumulated:
            layers_accumulated[name] = layer
        else:
            # Update fields
            layers_accumulated[name]['fields'].update(layer['fields'])
            # Update minzoom and maxzoom
            layers_accumulated[name]['minzoom'] = min(layers_accumulated[name]['minzoom'], layer['minzoom'])
            layers_accumulated[name]['maxzoom'] = max(layers_accumulated[name]['maxzoom'], layer['maxzoom'])

def get_layers_from_all_tiles_parallel(mbtiles_file, batch_size=10000, workers=4, verbose=True):
    """Extract layer information from all tiles in the MBTiles file."""
    conn = sqlite3.connect(mbtiles_file)
    cursor = conn.cursor()

    # Query the total number of tiles to set up progress tracking
    cursor.execute("SELECT COUNT(*) FROM tiles")
    total_tiles = cursor.fetchone()[0]

    layers = {}
    offset = 0

    with tqdm(total=total_tiles, desc="Processing tiles", disable=not verbose) as pbar:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = []
            # Process tiles in parallel batches
            while offset < total_tiles:
                cursor.execute("""SELECT tile_data, zoom_level FROM tiles ORDER BY zoom_level LIMIT ? OFFSET ?""", (batch_size, offset))
                tile_batch = cursor.fetchall()
                # Submit a batch for parallel decoding, along with the zoom level
                zoom_level = tile_batch[0][1] if tile_batch else None  # Get the zoom level from the first tile in the batch
                futures.append(executor.submit(decode_tile_batch, tile_batch, zoom_level))
                
                # Update offset for the next batch
                offset += batch_size
            
            # As tasks complete, update progress and collect layer names
            for future in as_completed(futures):
                new_layers = future.result()  # This should return a dictionary
                merge_layer_dicts(layers, new_layers)
                pbar.update(batch_size)  

    cursor.close()
    conn.close()
    
    # Format the layers into a JSON-compatible structure
    json_output = {
        "vector_layers": []
    }
    
    for layer_name, info in layers.items():
        json_output["vector_layers"].append({
            "id": layer_name,
            "fields": info["fields"],
            "minzoom": info["minzoom"],
            "maxzoom": info["maxzoom"],
        })
    return json_output

def fix_vectormetadata(input_mbtiles, compression_type, desc, verbose=True):
    conn = sqlite3.connect(input_mbtiles)       
    cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS metadata (name TEXT, value TEXT);')
    cursor.execute('create unique index IF NOT EXISTS name on metadata (name);')    

    # Update name and description
    name = os.path.basename(input_mbtiles)
    cursor.execute("INSERT OR IGNORE INTO metadata (name, value) VALUES (?, ?)", ('name', name))
    
    cursor.execute("INSERT OR IGNORE INTO metadata (name, value) VALUES (?, ?)", ('description', desc))

    # Update format to pbf 
    cursor.execute("INSERT OR REPLACE INTO metadata (name, value) VALUES (?, ?)", ('format', 'pbf'))
   
    # Update compression
    cursor.execute("INSERT OR REPLACE INTO metadata (name, value) VALUES (?, ?)", ('compression', compression_type))
    
    # Update min zoom, max zoom
    min_zoom, max_zoom = get_zoom_levels(input_mbtiles)
    cursor.execute("INSERT OR REPLACE INTO metadata (name, value) VALUES (?, ?)", ('minzoom', min_zoom))
    cursor.execute("INSERT OR REPLACE INTO metadata (name, value) VALUES (?, ?)", ('maxzoom', max_zoom))

    # Update bounds and center
    bounds, center = get_bounds_center(input_mbtiles)
    if bounds:
        cursor.execute("INSERT OR REPLACE INTO metadata (name, value) VALUES (?, ?)", ('bounds', bounds))
    if center:
        cursor.execute("INSERT OR REPLACE INTO metadata (name, value) VALUES (?, ?)", ('center', center))
    
    # update json
    print('Updating json vector_layers')
    batch_size=10000
    workers=4
    layers_json = get_layers_from_all_tiles_parallel(input_mbtiles,batch_size,workers,verbose)
    layers_json_str = json.dumps(layers_json)
    if layers_json_str:
        cursor.execute("INSERT OR REPLACE INTO metadata (name, value) VALUES (?, ?)", ('json', layers_json_str))

    conn.commit()
    conn.close() 

    logger.info(f'Fix metadata for {name} done!')

def fix_rastermetadata(input_mbtiles, format,desc):
    conn = sqlite3.connect(input_mbtiles)       
    cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS metadata (name TEXT, value TEXT);')
    cursor.execute('create unique index IF NOT EXISTS name on metadata (name);')    

    # Update name and description
    name = os.path.basename(input_mbtiles)
    cursor.execute("INSERT OR IGNORE INTO metadata (name, value) VALUES (?, ?)", ('name', name))
    cursor.execute("INSERT OR IGNORE INTO metadata (name, value) VALUES (?, ?)", ('description', desc))
   
    # Update format to raster
    cursor.execute("INSERT OR REPLACE INTO metadata (name, value) VALUES (?, ?)", ('format',format))

  
    # Update min zoom, max zoom
    min_zoom, max_zoom = get_zoom_levels(input_mbtiles)
    cursor.execute("INSERT OR REPLACE INTO metadata (name, value) VALUES (?, ?)", ('minzoom', min_zoom))
    cursor.execute("INSERT OR REPLACE INTO metadata (name, value) VALUES (?, ?)", ('maxzoom', max_zoom))

    # Update bounds and center
    bounds, center = get_bounds_center(input_mbtiles)
    if bounds:
        cursor.execute("INSERT OR REPLACE INTO metadata (name, value) VALUES (?, ?)", ('bounds', bounds))
    if center:
        cursor.execute("INSERT OR REPLACE INTO metadata (name, value) VALUES (?, ?)", ('center', center))
    conn.commit()
    conn.close() 

def main():
    parser = argparse.ArgumentParser(description='Create or update metadata for an existing MBTiles file.')
    parser.add_argument('input', help='Path to the MBTiles file.')
    parser.add_argument('-v', '--verbose', action=argparse.BooleanOptionalAction, default=True, help='Show progress bar')
    args = parser.parse_args()
    input_mbtiles = args.input
    
    if (os.path.exists(input_mbtiles)):
        is_vector, compression_type = check_vector(input_mbtiles) 
        tile_format = determine_tileformat(input_mbtiles)
        desc = 'Update metadata by vtiles.mbtiles.mbtilesfixmeta' 
        if is_vector:
            fix_vectormetadata(input_mbtiles, compression_type,desc, args.verbose)   
        else:
            fix_rastermetadata(input_mbtiles, tile_format,desc)        
    else: 
        logger.error ('MBTiles file does not exist!. Please recheck and input a correct file path.')
        sys.exit(1)

if __name__ == "__main__":
    main()
