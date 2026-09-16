#!/usr/bin/env python
import sys
import pprint
import requests
from io import BytesIO
from urllib.parse import urlparse
from .reader import Reader, MmapSource

def print_usage():
    print("Usage: pmtilesinfo PMTILES_FILE_OR_URL")
    print("Usage: pmtilesinfo PMTILES_FILE_OR_URL Z X Y")
    exit(1)

def is_url(path):
    return urlparse(path).scheme in ("http", "https")

def main():
    if len(sys.argv) <= 1:
        print_usage()

    pmtiles_path = sys.argv[1]

    try:
        # Check if path is a URL and fetch data
        if is_url(pmtiles_path):
            response = requests.get(pmtiles_path)
            response.raise_for_status()
            file_data = BytesIO(response.content)
        else:
            file_data = open(pmtiles_path, "r+b")

        with file_data as f:
            reader = Reader(MmapSource(f))
            if len(sys.argv) == 2:
                pprint.pprint(reader.header())
                pprint.pprint(reader.metadata())
            elif len(sys.argv) == 5:
                z = int(sys.argv[2])
                x = int(sys.argv[3])
                y = int(sys.argv[4])
                tile_data = reader.get(z, x, y)
                sys.stdout.buffer.write(tile_data)
            else:
                print_usage()

    except Exception as e:
        print(f"Error: {e}")
        exit(1)

if __name__ == "__main__":
    main()
