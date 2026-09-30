import sqlite3, argparse, sys, logging, os, json
from tqdm import tqdm
from vtiles.utils.geopreocessing import flip_y, check_vector
from vtiles.mbtiles.mbtilesfixmeta import fix_rastermetadata, fix_vectormetadata,determine_tileformat

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def mbtiles_connect(mbtiles_file):
  try:
    conn = sqlite3.connect(mbtiles_file)
    return conn
  except Exception as e:
    logger.error("Could not connect to MBTiles file")
    logger.exception(e)
    sys.exit(1)

def mbtiles_init(cur):
  cur.execute("""
    create table tiles (
      zoom_level integer,
      tile_column integer,
      tile_row integer,
      tile_data blob);
      """)
  cur.execute("""create unique index tile_index on tiles(zoom_level, tile_column, tile_row);""")

def optimize_connection(cur):
  cur.execute("""PRAGMA synchronous=0""")
  # cur.execute("""PRAGMA locking_mode=EXCLUSIVE""")
  cur.execute("""PRAGMA journal_mode=DELETE""")

def import_metadata(input_mbtiles, metadata_json):
  conn = sqlite3.connect(input_mbtiles)       
  cur = conn.cursor()
  cur.execute('CREATE TABLE metadata (name TEXT, value TEXT);')
  cur.execute('CREATE UNIQUE INDEX name on metadata (name);')
  for name, value in metadata_json.items():
    cur.execute('insert into metadata (name, value) values (?, ?)',(name, value))
  

def get_dirs(path):
  return [name for name in os.listdir(path)
    if os.path.isdir(os.path.join(path, name))]

def folder2mbtiles(input_folder, mbtiles_file, flipy=0, verbose=True):
  # logger.debug("%s --> %s" % (input_folder, mbtiles_file))
  con = mbtiles_connect(mbtiles_file)
  cur = con.cursor()
  optimize_connection(cur)
  mbtiles_init(cur)  

  with tqdm(desc="Coverting tiles", unit=" tiles", disable=not verbose) as pbar:
    for zoom_dir in get_dirs(input_folder):   
      z = int(zoom_dir)
      for row_dir in get_dirs(os.path.join(input_folder, zoom_dir)):
        x = int(row_dir)
        for current_file in os.listdir(os.path.join(input_folder, zoom_dir, row_dir)):
          if current_file == ".DS_Store":
            logger.warning("The .DS_Store file will be ignored.")
          else:
            # file_name, ext = current_file.split('.',1)
            file_name, ext = os.path.splitext(current_file)       
            if ext in ('.png','.jpg','.jpeg','.webp','.pbf','.mvt'):
              f = open(os.path.join(input_folder, zoom_dir, row_dir, current_file), 'rb')
              file_content = f.read()
              f.close()
              if flipy == 1:
                y = flip_y(int(z), int(file_name))
              else:
                y = int(file_name)
              logger.debug(' Read tile from Zoom (z): %i\tCol (x): %i\tRow (y): %i' % (z, x, y))
              cur.execute("""insert into tiles (zoom_level,
                  tile_column, tile_row, tile_data) values
                  (?, ?, ?, ?);""",
                  # (z, x, y, file_content))
                  (z, x, y, sqlite3.Binary(file_content)))
              pbar.update(1)

  cur.close()
  con.commit()
  con.close()    
  logger.info('Converting Folder to MBTiles done.')

  # converting or fixing metadata
  metadata = os.path.join(input_folder, 'metadata.json')
  if os.path.exists(metadata):
    metadata_json = json.load(open(metadata, 'r'))
    import_metadata(mbtiles_file, metadata_json)
    logger.info('Converting metadata done.') 
  else:
    is_vector, compression_type = check_vector(mbtiles_file) 
    tile_format = determine_tileformat(mbtiles_file)
    desc = 'MBtiles created by vtiles.mbtiles.folder2mbtiles and metadata updated by mbtilesfixmeta' 
    if is_vector:
        fix_vectormetadata(mbtiles_file, compression_type,desc, verbose)   
    else:
        fix_rastermetadata(mbtiles_file, tile_format,desc)     
   

def main():
  logging.basicConfig(level=logging.INFO, format='%(message)s')
  parser = argparse.ArgumentParser(description='Convert Tiles folder to MBTiles')
  parser.add_argument('input', help='Input folder')
  parser.add_argument('-o','--output', default=None, help='Output mbtiles file name (optional)')
  parser.add_argument('-flipy', type=int, default=0,choices=[0, 1], help='TMS <--> XYZ tiling scheme (optional): 1 or 0, default is 0')
  parser.add_argument('-v', '--verbose', action=argparse.BooleanOptionalAction, default=True, help='Show progress bar')

  args = parser.parse_args()

  if not os.path.exists(args.input) or not os.path.isdir(args.input):
    logger.error('Input folder does not exist or invalid!. Please recheck and input a correct one.')
    sys.exit(1)
  input_folder_abspath =  os.path.abspath(args.input)  

  if args.output:
      output_file_abspath = os.path.abspath(args.output)
      if os.path.exists(output_file_abspath):
        logger.error(f'Output MBTiles file {output_file_abspath} already exists!. Please recheck and input a correct one. Ex: -o tiles.mbtiles')
        sys.exit(1)
      elif not output_file_abspath.endswith('mbtiles'):
        logger.error(f'Output MBTiles file {output_file_abspath} must end with .mbtiles. Please recheck and input a correct one. Ex: -o tiles.mbtiles')
        sys.exit(1)
  else:
    output_file_name = os.path.basename(input_folder_abspath) + '.mbtiles' 
    output_file_abspath = os.path.join(os.path.dirname(args.input), output_file_name)    
    if os.path.exists(output_file_abspath): 
      logger.error(f'Output MBTiles file {output_file_abspath} already exists! Please recheck and input a correct one. Ex: -o tiles.mbtiles')
      sys.exit(1)          

  # Inform the user of the conversion
  logging.info(f'Converting {input_folder_abspath} to {output_file_abspath}.') 
  folder2mbtiles(input_folder_abspath, output_file_abspath, args.flipy, args.verbose)

if __name__ == "__main__":
  main()
