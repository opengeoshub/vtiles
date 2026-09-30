import os,sys,argparse, logging
from vtiles.utils.mapbox_vector_tile import encode
from vtiles.utils.geojson2vt.geojson2vt import geojson2vt
import sqlite3,json, gzip
from vtiles.mbtiles.mbtilesfixmeta import fix_vectormetadata

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_mbtiles(mbtiles_file):
    try:
        conn = sqlite3.connect(mbtiles_file)
        cursor = conn.cursor()

        # Create metadata table
        cursor.execute('CREATE TABLE metadata (name TEXT, value TEXT);')
        cursor.execute('CREATE UNIQUE INDEX name ON metadata (name);')

        # Create tiles table
        cursor.execute('CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB);')
        cursor.execute('CREATE UNIQUE INDEX tile_index ON tiles (zoom_level, tile_column, tile_row);')

        # Commit the transaction
        conn.commit()

    except sqlite3.Error as e:
        logger.error(f"Error occurred while creating MBTiles file: {e}")
        if conn:
            conn.rollback()

    finally:
        # Close the cursor and the connection
        if cursor:
            cursor.close()  # Ensure cursor is explicitly closed
        if conn:
            conn.close()    # Ensure connection is closed

def add_tile_to_mbtiles(mbtiles_file, z, x, y, tile_data):
    """Add a tile to the MBTiles database."""
    try:
        # Open the database connection
        conn = sqlite3.connect(mbtiles_file)
        cursor = conn.cursor()

        # Insert or replace the tile into the tiles table
        cursor.execute('''
            INSERT OR REPLACE INTO tiles (zoom_level, tile_column, tile_row, tile_data) 
            VALUES (?, ?, ?, ?);
        ''', (z, x, y, tile_data))

        # Commit the changes
        conn.commit()

    except sqlite3.Error as e:
        print(f"Error occurred while adding a tile: {e}")
        if conn:
            conn.rollback()
    finally:
        # Close cursor and connection
        if cursor:
            cursor.close()
        if conn:
            conn.close()


GEOJSON_TYPES = {
    'FeatureCollection', 'Feature',
    'Point', 'MultiPoint', 'LineString', 'MultiLineString',
    'Polygon', 'MultiPolygon', 'GeometryCollection',
}


def extract_layers(geojson_data, default_layer_name):
    """Return {layer_name: FeatureCollection} from standard or layer-keyed GeoJSON."""
    if not isinstance(geojson_data, dict):
        raise ValueError('Input data is not a valid GeoJSON object.')

    geojson_type = geojson_data.get('type')
    if geojson_type in GEOJSON_TYPES:
        return {default_layer_name: _as_feature_collection(geojson_data)}

    layers = {}
    for name, value in geojson_data.items():
        if isinstance(value, dict) and value.get('type') in GEOJSON_TYPES:
            layers[name] = _as_feature_collection(value)

    if not layers:
        raise ValueError('Input data is not a valid GeoJSON object.')
    return layers


def _as_feature_collection(geojson):
    geojson_type = geojson.get('type')
    if geojson_type == 'FeatureCollection':
        return geojson
    if geojson_type == 'Feature':
        return {'type': 'FeatureCollection', 'features': [geojson]}
    return {
        'type': 'FeatureCollection',
        'features': [{'type': 'Feature', 'geometry': geojson, 'properties': {}}]
    }


def transform_to_layer(data, layer_name):
    """
    Transforms the input dictionary into a list format with a specified layer name.

    Args:
        data (dict): The input dictionary containing features and metadata.
        layer_name (str): The name to be assigned to the layer.

    Returns:
        list: A list containing the transformed dictionary with the specified layer name.
    """
    transformed_data = [{
        "name": layer_name,
        "features": data.get('features', [])
        # 'numPoints': data.get('numPoints'),
        # 'numSimplified': data.get('numSimplified'),
        # 'numFeatures': data.get('numFeatures'),
        # 'source': data.get('source', []),
        # 'x': data.get('x'),
        # 'y': data.get('y'),
        # 'z': data.get('z'),
        # 'transformed': data.get('transformed'),
        # 'minX': data.get('minX'),
        # 'minY': data.get('minY'),
        # 'maxX': data.get('maxX'),
        # 'maxY': data.get('maxY')
    }]
    
    for feature_collection in transformed_data:
        for feature in feature_collection['features']:
            # Convert 'geometry' based on type
            if feature['type'] == 1:  # Point
                coords = feature['geometry']
                coords[1] = 4096 - coords[1]  # Apply y-axis inversion
                feature['geometry'] = f"POINT({coords[0]} {coords[1]})"
            elif feature['type'] == 2:  # LineString
                coords = feature['geometry']
                coords = [(x, 4096 - y) for x, y in coords]  # Apply y-axis inversion to each coordinate
                coords_str = ', '.join([f"{x} {y}" for x, y in coords])
                feature['geometry'] = f"LINESTRING({coords_str})"
            elif feature['type'] == 3:  # Polygon
                coords = feature['geometry'][0]
                coords = [(x, 4096 - y) for x, y in coords]  # Apply y-axis inversion to each coordinate
                coords_str = ', '.join([f"{x} {y}" for x, y in coords])
                feature['geometry'] = f"POLYGON(({coords_str}))"
            
            # Rename 'tags' to 'properties'
            feature['properties'] = feature.pop('tags')

            # Remove 'type' as it's no longer needed
            del feature['type']


    return transformed_data


def main():
    parser = argparse.ArgumentParser(description="Convert GeoJSON to MBTiles.")
    parser.add_argument('input', help='Input GeoJSON file.')
    parser.add_argument('-o', '--output', help='Output MBTiles file.')
    parser.add_argument('-z', '--zoom', type=int, default=0, help="Zoom level for the tile.")
    parser.add_argument('-x', '--x', type=int, default=0, help="Tile column.")
    parser.add_argument('-y', '--y', type=int, default=0, help="Tile row.")
    parser.add_argument('-v', '--verbose', action=argparse.BooleanOptionalAction, default=True, help='Show progress bar')
    
    args = parser.parse_args()
    if not os.path.exists(args.input):
        logging.error('Input GeoJSON file does not exist! Please recheck and input a correct file path.')
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
        output_file_name = os.path.basename(input_file_abspath).replace('.geojson', '.mbtiles')
        output_file_abspath = os.path.join(os.path.dirname(input_file_abspath), output_file_name)
 
        if os.path.exists(output_file_abspath): 
            logger.error(f'Output MBTiles  {output_file_abspath} already exists! Please recheck and input a correct one. Ex: -o tiles.mbtiles')
            sys.exit(1)          

    logging.info(f'Converting {input_file_abspath} to {output_file_abspath}.')

    with open(input_file_abspath, 'r',encoding='utf-8') as f:
        geojson_data = json.load(f)

    default_layer_name = os.path.splitext(os.path.basename(input_file_abspath))[0]
    try:
        layers = extract_layers(geojson_data, default_layer_name)
    except ValueError as e:
        logger.error(str(e))
        sys.exit(1)

    z, x, y = args.zoom, args.x, args.y
    max_zoom = max(z, 5)
    tile_options = {
        'maxZoom': max_zoom,
        'tolerance': 3,
        'extent': 4096,
        'buffer': 64,
        'lineMetrics': False,
        'promoteId': None,
        'generateId': False,
        'indexMaxZoom': max_zoom,
        'indexMaxPoints': 100000
    }

    encoded_layers = []
    for layer_name, layer_geojson in layers.items():
        tile_index = geojson2vt(layer_geojson, tile_options, logging.INFO)
        tile_data = tile_index.get_tile(z, x, y)
        if not tile_data or not tile_data.get('features'):
            logger.warning(f'No features for layer {layer_name} at tile {z}/{x}/{y}')
            continue
        encoded_layers.extend(transform_to_layer(tile_data, layer_name))

    if not encoded_layers:
        logger.error(f'No features found at tile {z}/{x}/{y}.')
        sys.exit(1)

    tile_data_fixed_encoded = encode(encoded_layers)
    tile_data_fixed_encoded_compressed = gzip.compress(tile_data_fixed_encoded)

    create_mbtiles(output_file_abspath)
    add_tile_to_mbtiles(output_file_abspath, z, x, y, tile_data_fixed_encoded_compressed)

    desc = 'Update metadata by vtiles.mbtiles.mbtilesfixmeta'
    fix_vectormetadata(output_file_abspath, 'GZIP', desc, args.verbose)
    logging.info(f'Converting GeoJSON to MBTiles done!')


if __name__ == "__main__":
    main()
