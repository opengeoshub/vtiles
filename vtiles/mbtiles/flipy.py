#!/usr/bin/env python
import os, logging
import shutil
import sys
import argparse
from tqdm import tqdm
from vtiles.utils.geopreocessing import safe_makedir

logger = logging.getLogger(__name__)

def flip_y(inDIR, copyDIR, verbose=True):
    # Copy all files from the root of inDIR to the root of copyDIR, including metadata.json
    root_files = [f for f in os.listdir(inDIR) if os.path.isfile(os.path.join(inDIR, f))]
    for root_file in tqdm(root_files, desc="Copying metadata (if existed)", unit=' ', ncols=80, bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{percentage:.0f}%]', disable=not verbose):
        shutil.copy(os.path.join(inDIR, root_file), os.path.join(copyDIR, root_file))

    # Count the total number of files to process
    total_files = sum([len(files) for rVal, dName, files in os.walk(inDIR) if rVal != inDIR])

    # Initialize the progress bar for nested files
    with tqdm(total=total_files, desc="Processing files", unit=' ', ncols=80, bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{percentage:.0f}%]', disable=not verbose) as pbar:
        for rVal, dName, fList in os.walk(inDIR):
            # Skip the root directory as it has already been handled
            if rVal == inDIR:
                continue

            # Calculate the relative path for the new directory structure
            relPath = os.path.relpath(rVal, inDIR)
            newpath = os.path.join(copyDIR, relPath)
            if not os.path.exists(newpath):
                os.makedirs(newpath)

            for fileName in fList:
                zxParts = os.path.normpath(relPath).split(os.sep)
                if len(zxParts) < 2:
                    print(f"Skipping file due to insufficient path depth: {fileName}")
                    continue

                z = int(zxParts[0])
                y = int(fileName.split(".")[0])
                fileExtension = fileName.split(".")[1]
                newY = str((2**z - 1) - y) + "." + fileExtension
                shutil.copyfile(os.path.join(rVal, fileName), os.path.join(newpath, newY))

def main():
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    
    # Argument parser setup with input folder as a positional argument
    parser = argparse.ArgumentParser(description='Convert TMS <--> XYZ tiling scheme for a tiles folder')
    parser.add_argument('input', help='Input folder containing tiles')
    parser.add_argument('-o', '--output', default=None, help='Output folder (optional)')
    parser.add_argument('-v', '--verbose', action=argparse.BooleanOptionalAction, default=True, help='Show progress bar')
    args = parser.parse_args()

    # Validate input folder
    if not os.path.exists(args.input) or not os.path.isdir(args.input):
        logging.error('Input folder does not exist or is invalid. Please provide a valid folder.')
        sys.exit(1)

    input_folder_abspath = os.path.abspath(args.input)

    # Determine the output folder
    if args.output:
        output_folder_abspath = os.path.abspath(args.output)
    else:
        input_folder_name = os.path.basename(input_folder_abspath)
        output_folder_abspath = os.path.join(os.path.dirname(input_folder_abspath), f"{input_folder_name}_flipy")

    # Create output folder if it doesn't exist
    if not os.path.exists(output_folder_abspath):
        os.makedirs(output_folder_abspath)
    else:         
        logging.error(f'Output folder {output_folder_abspath} already exists. Please provide a valid folder with -o.')
        sys.exit(1)

    # Inform the user of the conversion
    logging.info(f'Converting folder {input_folder_abspath} to {output_folder_abspath}')
    
    # Call the conversion function
    flip_y(input_folder_abspath, output_folder_abspath, args.verbose)

if __name__ == "__main__":
    main()