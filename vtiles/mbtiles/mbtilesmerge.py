import sqlite3
import os, sys
import shutil
from vtiles.utils.mapbox_vector_tile import encode, decode
from vtiles.utils.geopreocessing import fix_wkt, check_vector
import argparse
import gzip, zlib
import json
import logging
from tqdm import tqdm
from vtiles.mbtiles.mbtilesfixmeta import fix_vectormetadata

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def merge_json_layers(layer1, layer2):
    # Create a dictionary to combine features by layer name
    combined_layer = {}
    
    # Add features from the first JSON data
    for layer in layer1:
        name = layer['name']
        if name not in combined_layer:
            combined_layer[name] = layer
        else:
            combined_layer[name]['features'].extend(layer['features'])

    # Add features from the second JSON data
    for layer in layer2:
        name = layer['name']
        if name not in combined_layer:
            combined_layer[name] = layer
        else:
            combined_layer[name]['features'].extend(layer['features'])

    # Convert combined data to a list
    merged_layer= list(combined_layer.values())
    
    return merged_layer

def merge_tiles(tile1, tile2,z=None, x=None, y=None):
    try:        
        if tile1 and tile2:
            if tile1[:2] == b'\x1f\x8b':
                tile1 = gzip.decompress(tile1)
            elif tile1[:2] == b'\x78\x9c' or tile1[:2] == b'\x78\x01' or tile1[:2] == b'\x78\xda':
                tile1 = zlib.decompress(tile1)
            decoded_tile1 = decode(tile1)
            decoded_tile1_fixed = fix_wkt(decoded_tile1)

            if tile2[:2] == b'\x1f\x8b':
                tile2 = gzip.decompress(tile2)
            elif tile2[:2] == b'\x78\x9c' or tile2[:2] == b'\x78\x01' or tile2[:2] == b'\x78\xda':
                tile2 = zlib.decompress(tile2)
            decoded_tile2 = decode(tile2)
            decoded_tile2_fixed = fix_wkt(decoded_tile2)

            merged_layer = merge_json_layers(decoded_tile1_fixed,decoded_tile2_fixed)
            # print (merged_tiles)
            merged_tile_encoded = encode(merged_layer)
            merged_tile_encoded_gzip = gzip.compress(merged_tile_encoded)   
            return merged_tile_encoded_gzip
                
        elif tile1:
            if tile1[:2] == b'\x1f\x8b':
                return tile1
            elif tile1[:2] == b'\x78\x9c' or tile1[:2] == b'\x78\x01' or tile1[:2] == b'\x78\xda':
                tile1_decompressed_zlib = zlib.decompress(tile1)
                return gzip.compress(tile1_decompressed_zlib)
            else: return  gzip.compress(tile1)   
        
        elif tile2:
            if tile2[:2] == b'\x1f\x8b':
                return tile2
            elif tile2[:2] == b'\x78\x9c' or tile2[:2] == b'\x78\x01' or tile2[:2] == b'\x78\xda':
                tile2_decompressed_zlib = zlib.decompress(tile2)
                return gzip.compress(tile2_decompressed_zlib)     
            else: return  gzip.compress(tile2) 
    except Exception as e:
        return None

def merge_vector_layers(layer1, layer2):
    layer1_ids = {layer['id'] for layer in layer1}
    merged_layers = layer1[:]

    for layer in layer2:
        if layer['id'] in layer1_ids:
            continue  # Skip duplicate layers by 'id'
        merged_layers.append(layer)
    
    return merged_layers

def merge_tilestats(stats1, stats2):
    stats1_layers = {layer['layer']: layer for layer in stats1['layers']}
    merged_layers = stats1['layers'][:]

    for layer in stats2['layers']:
        if layer['layer'] in stats1_layers:
            stats1_layer = stats1_layers[layer['layer']]
            stats1_layer['count'] += layer['count']
            stats1_layer['attributeCount'] += layer['attributeCount']
            stats1_layer['attributes'].extend(layer['attributes'])
        else:
            merged_layers.append(layer)
    
    return {
        "layerCount": len(merged_layers),
        "layers": merged_layers
    }

def merge_json_metadata(json1, json2):
    if not json1:
        return json2
    if not json2:
        return json1

    dict1 = json.loads(json1)
    dict2 = json.loads(json2)

    merged_dict = {**dict1}

    if "vector_layers" in dict1 and "vector_layers" in dict2:
        merged_dict["vector_layers"] = merge_vector_layers(dict1["vector_layers"], dict2["vector_layers"])

    if "tilestats" in dict1 and "tilestats" in dict2:
        merged_dict["tilestats"] = merge_tilestats(dict1["tilestats"], dict2["tilestats"])

    return json.dumps(merged_dict)

def merge_metadata(metadata_dicts):
    merged_metadata = {}
    for metadata in metadata_dicts:
        for name, value in metadata.items():
            if name in merged_metadata:
                if name.strip() =='json':  # Check if the metadata name suggests JSON content
                    merged_metadata[name] = merge_json_metadata(merged_metadata[name], value)
                else:
                    # if merged_metadata[name] != value:
                    merged_metadata[name] += '; ' + value
            else:
                merged_metadata[name] = value
    return merged_metadata

def get_min_zoom(zoom_list):
    try:
        numbers_str = zoom_list.split(';')
        # Convert the number strings to integers or floats
        numbers = [int(num.strip()) for num in numbers_str]
        # Find the minimum value
        min_zoom = min(numbers)
        return str(min_zoom)
    except Exception as e:
        logging.error(f"Get min zoom error: {e}")
        return zoom_list
    
def get_max_zoom(zoom_list):
    try:
        numbers_str = zoom_list.split(';')
        # Convert the number strings to integers or floats
        numbers = [int(num.strip()) for num in numbers_str]
        # Find the minimum value
        max_zoom = max(numbers)
        return str(max_zoom)
    except Exception as e:
        logging.error(f"Get max zoom error: {e}")
        return zoom_list
    
def get_max_bound(bounds_str):
    try:
         # Initialize min and max values with None
        min_lon, min_lat, max_lon, max_lat = None, None, None, None        
        bounds_items = bounds_str.split(';')       
        # Initialize variables to store the min bound
        for item in bounds_items:
            # Extract coordinates from each bound
            coords = list(map(float, item.split(',')))
            if min_lon is None:
                # Initialize min and max with the first bounding box
                min_lon, min_lat, max_lon, max_lat = coords
            else:
                # Update min and max values
                min_lon = min(min_lon, coords[0])
                min_lat = min(min_lat, coords[1])
                max_lon = max(max_lon, coords[2])
                max_lat = max(max_lat, coords[3])
        # Return the max bound as a string
        max_bound = f"{min_lon},{min_lat},{max_lon},{max_lat}"
        return max_bound
    except Exception as e:
        logging.error(f"Get max bound error: {e}")
        return '-180.000000,-85.051129,180.000000,85.051129'

def get_center_of_bound(bounds_str):
    try:
        # Split the string into individual coordinates
        coords = [float(coord) for coord in bounds_str.split(',')]
        if len(coords) == 4:
            lon1, lat1, lon2, lat2 = coords
            # Calculate the center of the bounding box
            center_lon = (lon1 + lon2) / 2
            center_lat = (lat1 + lat2) / 2
            # Return the center as a formatted string
            return f"{center_lon},{center_lat}"
        else:
            raise ValueError("Invalid bounds string format")
    except Exception as e:
        logging.error(f"Get center of bound error: {e}")
        return ''
        
def merge_mbtiles(input_mbtiles, output_mbtiles, verbose=True):   
    is_vector, compression_type = check_vector(input_mbtiles[0]) 
    if is_vector:
        fix_vectormetadata(input_mbtiles[0], compression_type,'', verbose)   
        shutil.copyfile(input_mbtiles[0], output_mbtiles)
        try:
            conn_out = sqlite3.connect(output_mbtiles)       
            cur_out = conn_out.cursor()
            cur_out.execute('CREATE TABLE IF NOT EXISTS metadata (name TEXT, value TEXT)')
            cur_out.execute('DROP TABLE IF EXISTS tiles_new;')
            cur_out.execute('CREATE TABLE tiles_new (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB, PRIMARY KEY (zoom_level, tile_column, tile_row))')
            cur_out.execute('''
                INSERT INTO tiles_new (zoom_level, tile_column, tile_row, tile_data)
                SELECT zoom_level, tile_column, tile_row, tile_data FROM tiles;
                ''')
            
            cur_out.execute("SELECT type FROM sqlite_master WHERE name='tiles'")  
            result = cur_out.fetchone()
            if result:
                if result[0] == 'view':
                    cur_out.execute('DROP VIEW tiles')
                elif result[0] == 'table':
                    cur_out.execute('DROP TABLE tiles')
            cur_out.execute('ALTER TABLE tiles_new RENAME TO tiles')
            cur_out.execute('CREATE UNIQUE INDEX tile_index ON tiles (zoom_level, tile_column, tile_row)')
            
            # Merging tiles   
            cur_out.execute('SELECT zoom_level, tile_column, tile_row, tile_data FROM tiles ORDER BY zoom_level')          
            output_rows = cur_out.fetchall()
            tiles = {}

            for (z, x, y, tile) in output_rows:
                key = (z, x, y)
                tiles[key] = tile
            
            connections = [sqlite3.connect(mbtiles) for mbtiles in input_mbtiles]
            cursors_in = [conn.cursor() for conn in connections]
            for i, cursor in enumerate(cursors_in):
                if i == 0:
                    continue  # Skip the cursor for the first MBTiles file     
                is_vector, compression_type = check_vector(input_mbtiles[0]) 
                if is_vector:
                    fix_vectormetadata(input_mbtiles[i], compression_type,'', verbose)
                    mbtiles_name = os.path.basename(input_mbtiles[i])
                    cursor.execute('SELECT zoom_level, tile_column, tile_row, tile_data FROM tiles ORDER BY zoom_level')
                    rows = cursor.fetchall()
                    for (z, x, y, tile) in tqdm(rows, desc=f"Processing tiles from {mbtiles_name}", disable=not verbose):
                        key = (z, x, y)
                        if key in tiles:
                            tiles[key] = merge_tiles(tiles[key], tile, z, x, y)
                        else:
                            tiles[key] = tile

            for key, tile in tqdm(tiles.items(), desc="Inserting merged tiles", disable=not verbose):
                cur_out.execute('INSERT OR REPLACE INTO tiles (zoom_level, tile_column, tile_row, tile_data) VALUES (?, ?, ?, ?)', (key[0], key[1], key[2], tile))
            conn_out.commit()
            print(f"Successfully merged MBTiles files into {output_mbtiles}")
        except Exception as e:
            logging.error(f"Error Merging tile_data {mbtiles_name}: {e}")
        
        try: 
            # Merging metadata
            metadata_dicts = []
            for i, cursor in enumerate(cursors_in):
                mbtiles_name = os.path.basename(input_mbtiles[i])  
                cursor.execute('SELECT name, value FROM metadata')
                metadata_dicts.append({name: value for name, value in cursor.fetchall()})

            merged_metadata = merge_metadata(metadata_dicts)

            for name, value in tqdm(merged_metadata.items(), desc=f"Inserting merged metadata", disable=not verbose):
                cur_out.execute('INSERT OR REPLACE INTO metadata (name, value) VALUES (?, ?)', (name, value))

            # Update format
            cur_out.execute(''' UPDATE metadata SET value = 'pbf' where name = 'format' ''')
            
            # Update minzoom
            cur_out.execute("SELECT value FROM metadata WHERE name = 'minzoom'")
            zoom_levels = cur_out.fetchone()[0]  # Fetch the value
            if zoom_levels:
                min_zoom = get_min_zoom(zoom_levels)
                cur_out.execute('''
                    UPDATE metadata 
                    SET value = ? 
                    WHERE name = 'minzoom'
                ''', (min_zoom,))

            # Update maxzoom
            cur_out.execute("SELECT value FROM metadata WHERE name = 'maxzoom'")
            zoom_levels = cur_out.fetchone()[0]  # Fetch the value

            max_zoom = 0
            if zoom_levels:
                max_zoom = get_max_zoom(zoom_levels)
                cur_out.execute('''
                    UPDATE metadata 
                    SET value = ? 
                    WHERE name = 'maxzoom'
                ''', (max_zoom,))
            
            # Update max bounds
            cur_out.execute("SELECT value FROM metadata WHERE name = 'bounds'")
            bounds = cur_out.fetchone()[0]  # Fetch the value
            if bounds:
                min_bound = get_max_bound(bounds)

                cur_out.execute('''
                    UPDATE metadata 
                    SET value = ? 
                    WHERE name = 'bounds'
                    ''', (min_bound,))

            # Update center
            cur_out.execute("SELECT value FROM metadata WHERE name = 'bounds'")
            bound = cur_out.fetchone()[0]  
            center = get_center_of_bound(bound)
            center_of_bound = ''
            if center != '':
                center_of_bound = center +f',{max_zoom}'

            cur_out.execute('''
                UPDATE metadata 
                SET value = ? 
                WHERE name = 'center'
                ''', (center_of_bound,))

            # Update description
            description = 'Merge multiple MBTiles files into a single MBTiles file using mbtilesmerge from vtiles'
            cur_out.execute('''
                INSERT OR REPLACE INTO metadata (name, value)
                VALUES ('description', ?)
            ''', (description,))
        
            conn_out.commit()
            print(f"Successfully merged metadata into {output_mbtiles}")
            
        except Exception as e:
            logging.error(f"Error Merging metadata: {e}")

        finally:
            for conn in connections:
                conn.close()   
            conn_out.close()
    else:
        logging.info('Only vector mbtiles is supported.')
        return

def main():
    parser = argparse.ArgumentParser(description="Merge multiple vector MBTiles files into a single MBTiles file.")
    parser.add_argument('input', nargs='+', help='Paths to the input MBTiles files to merge.')
    parser.add_argument('-o', '--output', help='Output merged MBTiles file. Defaults to "merged.mbtiles" in the current directory.')
    parser.add_argument('-v', '--verbose', action=argparse.BooleanOptionalAction, default=True, help='Show progress bar')

    args = parser.parse_args()
    for file in args.input:
        if not os.path.exists(file):
            print(f"Error: Input file '{file}' does not exist.")
            sys.exit(1)  # Exit with an error code

    if args.output:
        output_file = os.path.abspath(args.output)
        if os.path.exists(output_file):
            logger.error(f'Output MBTiles file {output_file} already exists!. Please recheck and input a correct one. Ex: -o merged.mbtiles')
            sys.exit(1)
        elif not output_file.endswith('mbtiles'):
            logger.error(f'Output MBTiles file {output_file} must end with .mbtiles. Please recheck and input a correct one. Ex: -o merged.mbtiles')
            sys.exit(1)
    else:
        output_file = os.path.join(os.getcwd(), 'merged.mbtiles')
        if os.path.exists(output_file): 
            logger.error(f'Output MBTiles file {output_file} already exists! Please recheck and input a correct one. Ex: -o merged.mbtiles')
            sys.exit(1)          

    merge_mbtiles(args.input, output_file, args.verbose)


if __name__ == '__main__':
    main()