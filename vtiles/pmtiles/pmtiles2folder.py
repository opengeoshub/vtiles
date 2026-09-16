import argparse
import json
import os,sys, logging
from .reader import Reader, MmapSource, all_tiles
from tqdm import tqdm 

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

def pmtiles_to_folder(input_file, output_folder, verbose=False):   
    with open(input_file, "r+b") as f:
        source = MmapSource(f)
        reader = Reader(source)
        
        # Write metadata to a JSON file
        with open(os.path.join(output_folder, "metadata.json"), "w") as metadata_file:
            metadata_file.write(json.dumps(reader.metadata()))

        # Get total number of tiles for progress bar
        total_tiles = len(list(all_tiles(source)))
        
        # Iterate over all tiles and write them to the output folder
        for zxy, tile_data in tqdm(all_tiles(source), total=total_tiles, desc="Processing tiles", disable=not verbose):
            z, x, y = zxy
            directory = os.path.join(output_folder, str(z), str(x))
            os.makedirs(directory, exist_ok=True)
            path = os.path.join(directory, str(y) + ".pbf")  # Change extension as needed
            with open(path, "wb") as tile_file:
                tile_file.write(tile_data)

def main():
    parser = argparse.ArgumentParser(description='Convert PMTiles to tiles folder')
    parser.add_argument('input', help='Input PMTiles file path')
    parser.add_argument('-o', '--output',help='Output directory path')
    parser.add_argument('-v', '--verbose', action='store_true', help='Show progress bar')
    args = parser.parse_args()

    if not os.path.exists(args.input):
        logging.error('PMTiles file does not exist! Please recheck and input a correct file path.')
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
    pmtiles_to_folder(input_filename_abspath, output_folder_abspath, args.verbose)


if __name__ == "__main__":
    main()
