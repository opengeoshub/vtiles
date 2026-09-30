import os,sys, logging
import requests
import argparse
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def download_tile(z, x, y, url_template, output_folder, format, pbar):
    """Download a single tile and save it in a structured folder (z/x/y.pbf)."""
    tile_url = url_template.format(z=z, x=x, y=y)
    try:
        response = requests.get(tile_url, timeout=10)  # Added timeout for robustness
        if response.status_code == 200:
            tile_folder = os.path.join(output_folder, str(z), str(x))
            os.makedirs(tile_folder, exist_ok=True)
            tile_file = os.path.join(tile_folder, f'{y}.{format}')
            with open(tile_file, 'wb') as f:
                f.write(response.content)
            pbar.update(1)  # Update the progress bar only on success
        else:
            logger.error(f"Failed to download tile {z}/{x}/{y}: {response.status_code}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Error downloading tile {z}/{x}/{y}: {str(e)}")

def download_tiles(url, output_folder, minzoom, maxzoom, format, verbose=True):
    """Download all tiles from minzoom to maxzoom in a structured folder with a progress bar."""
    total_tiles = sum((2 ** z) ** 2 for z in range(minzoom, maxzoom + 1))
    chunk_size = 10  # Set the chunk size
    with tqdm(total=total_tiles, desc="Processing tiles", unit="tiles ", disable=not verbose) as pbar:
        for z in range(minzoom, maxzoom + 1):
            num_tiles = 2 ** z
            tile_downloads = []  # List to hold the tile download tasks
            for x in range(num_tiles):
                for y in range(num_tiles):
                    tile_downloads.append((z, x, y))
                    # Process in chunks of size `chunk_size`
                    if len(tile_downloads) == chunk_size:
                        with ThreadPoolExecutor(max_workers=10) as executor:
                            futures = [
                                executor.submit(download_tile, z, x, y, url, output_folder, format, pbar)
                                for z, x, y in tile_downloads
                            ]
                            for future in futures:
                                future.result()  # Ensure all futures are completed
                        tile_downloads = []  # Reset for the next chunk
            
            # Process any remaining tiles that didn't fill a complete chunk
            if tile_downloads:
                with ThreadPoolExecutor(max_workers=10) as executor:
                    futures = [
                        executor.submit(download_tile, z, x, y, url, output_folder, format, pbar)
                        for z, x, y in tile_downloads
                    ]
                    for future in futures:
                        future.result()  # Ensure all futures are completed

def main():
    parser = argparse.ArgumentParser(description='Convert MBTiles file to tiles folder')
    parser.add_argument('url', help='URL for vector tiles (e.g., https://your-vector-tile-server/{z}/{x}/{y}.pbf)')
    parser.add_argument('-o', '--output',help='Output folder name (optional)')
    parser.add_argument('-minzoom', type=int, default=0, help='Min zoom to export (optional, default is 0)')
    parser.add_argument('-maxzoom', type=int, default=8, help='Max zoom to export (optional, default is 8')
    parser.add_argument('-format', type=str, required=True, choices=['pbf', 'png', 'jpg', 'jpeg', 'webp', 'pbf', 'mvt'], help='tile format from the URL')
    parser.add_argument('-v', '--verbose', action=argparse.BooleanOptionalAction, default=True, help='Show progress bar')

    args = parser.parse_args()
    
    if args.output:
        output_folder_abspath = os.path.abspath(args.output)
    else:
        output_folder_abspath = os.path.join(os.getcwd(),'url2folder')

    # Create output folder if it doesn't exist
    if not os.path.exists(output_folder_abspath):
        os.makedirs(output_folder_abspath)
    else:         
        logging.error(f'Output folder {output_folder_abspath} already existed. Please provide a valid folder with -o.')
        sys.exit(1)

    # Inform the user of the conversion
    logging.info(f'Downloading tiles from  {args.url} to {output_folder_abspath} folder.')
    download_tiles(args.url, output_folder_abspath,args.minzoom, args.maxzoom, args.format, args.verbose)
    logging.info(f'Downloading tiles done!')


if __name__ == '__main__':
    main()
