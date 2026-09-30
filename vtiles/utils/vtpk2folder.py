import zipfile
import argparse, sys, os
from tqdm import tqdm
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def extract_vtpk(vtpk_path, output_dir, verbose=True):
    # Open the VTPK file
    with zipfile.ZipFile(vtpk_path, 'r') as zip_ref:
        # Get the list of files in the archive
        file_list = zip_ref.namelist()
        
        # Use tqdm to display a progress bar while extracting files
        for file in tqdm(file_list, desc="Extracting VTPK", unit="file", disable=not verbose):
            zip_ref.extract(file, output_dir)

    logger.info(f'Extracted VTPK to {output_dir} done!')

def main():
    parser = argparse.ArgumentParser(description='Extract VTPK (Vector Tile Package) to folder')
    parser.add_argument('input', help='Path to the input VTPK file')
    parser.add_argument('-o', '--output', help='Path to the output directory')
    parser.add_argument('-v', '--verbose', action=argparse.BooleanOptionalAction, default=True, help='Show progress bar')

    args = parser.parse_args()

    if not os.path.exists(args.input):
        logging.error('VTPK file does not exist! Please recheck and input a correct file path.')
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
    extract_vtpk(input_filename_abspath, output_folder_abspath, args.verbose)

if __name__ == '__main__':
    main()
