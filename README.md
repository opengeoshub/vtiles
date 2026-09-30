# VTiles - Vector Tiles Utilities

## Installation: 
[![PyPI version](https://badge.fury.io/py/vtiles.svg)](https://badge.fury.io/py/vtiles)
[![PyPI downloads](https://img.shields.io/pypi/dm/vtiles.svg)](https://pypistats.org/packages/vtiles)
![Downloads](https://static.pepy.tech/personalized-badge/vtiles?period=total&units=international_system&left_color=grey&right_color=blue&left_text=total)
[![image](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

- Using pip:
  ``` bash 
  pip install vtiles --upgrade
  ```
    
## Usage:
### MBTILES Utilities:
#### mbtilesinfo
- Show MBTiles metadata info, support raster MBTiles and vector MBTiles
- **mbtilesinfo** can show information from metadata table, total number of tiles, and vector_layers list for vector mbtiles 
  ``` bash 
  > mbtilesinfo <file_path>
  ```

#### mbtilesinspect
- Inspect MBTiles in actual tiles data instead of reading from metadata: 
- **mbtilesinspect** can show minzoom, maxzoom, total number of tiles, tile compression type, number of tiles comparing to standard tiles number at each zoom level, and it can show the duplicated rows in terms of zoom_level, tile_column, and tile_row
  ``` bash 
  > mbtilesinspect <file_path>
  ```
Ex: `> mbtilesinspect tiles.mbtiles`

#### mbtilesdelduplicate
- Remove duplicate tiles from an MBTiles file (same `zoom_level`, `tile_column`, and `tile_row`). Keeps the first occurrence of each tile and adds a unique index to prevent future duplicates.
  ``` bash 
  > mbtilesdelduplicate <input file> -o [output file (optional)]
  ```
Ex: `> mbtilesdelduplicate tiles.mbtiles -o tiles_clean.mbtiles`

  Without `-o`, the output is saved as `{input}_delduplicate.mbtiles` in the same folder as the input file.


#### mbtiles2folder
- Convert MBTiles file to folder: (support raster MBTiles (.png, .jpg, .webp) and vector MBTiles (.pbf)) 
  ``` bash 
  > mbtiles2folder  <file_name.mbtiles> -o [output_folder (optional, current dir if not specified)] -flipy [TMS <--> XYZ tiling scheme (optional): 1 or 0, default is 0] -minzoom [optional, default is 0] -maxzoom [Maximum zoom level to export (optional, default is maxzoom from input MBTiles]
  ```
  Ex: `> mbtiles2folder tiles.mbtiles -o tiles_folder -flipy 0 -minzoom 0 -maxzoom 6`

#### url2folder
- Download tiles from a tile server to tiles folders: 
  ``` bash 
  > url2folder -url <URL> -o <output_folder> -minzoom <min zoom> -maxzoom <max zoom>
  ```
  Ex: `> url2folder -url -o tiles.mbtiles -minzoom 0 -maxzoom 1 `

#### folder2mbtiles
- Convert a tiles folder to MBTiles file: (support raster tile (.png, .jpg, .webp) and vector tile (.pbf))
  ``` bash 
  > folder2mbtiles  <input_folder> -o [file_name.mbtiles (optional)] -flipy [TMS <--> XYZ tiling scheme (optional): 1 or 0, default is 0]
  ```
  Ex: `> folder2mbtiles  tiles_folder -o tiles.mbtiles -flipy 0`
  
  Without -o parameter: file_name.mbtiles has the same name with <input_folder> name at the current directory 

#### mbtiles2geojson
- Convert MBTiles to GeoJSON.
  ``` bash 
  > mbtiles2geojson  <input file> -o <Output GeoJSON> -z <zoom level> -flipy [TMS <--> XYZ tiling scheme (optional): 1 or 0, default is 0] -l [List of layer names to convert, all layers if not specified]
  ```
  Ex: `> mbtiles2geojson  tiles.mbtiles -o geojson.geojson -z 0 -flipy 0 -l water building`

#### geoson2mbtiles
- Convert geojson file to mbtiles (need tippecanoe to be installed)
  ``` bash 
  > geojson2mbtiles  <input files> -z <maxzoom> -o <output> -t <tippecanoe path> --extra-args <drop-densest-as-needed or coalesce-densest-as-needed or extend-zooms-if-still-dropping>
  ```
  Ex: `> geojson2mbtiles  state.geojson district.geojson -z9 -o state_district.mbtiles -t /usr/local/bin/ --extra-args coalesce-densest-as-needed` (on Linux)

#### folder2s3
- Upload a vector/raster tiles folder to Amazon S3 or S3-compatible storage (e.g. Cloudflare R2):
  ``` bash 
  > folder2s3  <input_folder> -format <'pbf', 'mvt', 'png', 'jpg', 'jpeg', 'webp'> [-v]
  ```
  Ex: `> folder2s3  vectortiles_folder -format pbf -v`
 
  Input S3 parameters:

  ```bash
  > S3 Bucket name: <Your S3 Bucket name (required)>
  > S3 Prefix: [Your S3 prefix (Optional. Press Enter to upload to the bucket root folder)]
  > S3 endpoint URL: [Press Enter for AWS S3; for Cloudflare R2: https://<ACCOUNT_ID>.r2.cloudflarestorage.com]
  > AWS Access Key ID: <Your_Access_Key_ID (required)>
  > AWS Secret Access Key: <Your_Secrect_Access_Key (required)>
  > AWS Region: [AWS region, or auto for Cloudflare R2]
  ```

#### pmtiles2s3
- Upload a PMTiles file to Amazon S3 or S3-compatible storage (e.g. Cloudflare R2). Uses multipart upload for large files:
  ``` bash
  > pmtiles2s3 <input.pmtiles> [-v]
  ```
  Ex: `> pmtiles2s3 vietnam.pmtiles -v`

  Input S3 parameters (same prompts as `folder2s3`):

  ```bash
  > S3 Bucket name: <Your S3 Bucket name (required)>
  > S3 Prefix: [Optional; file is uploaded as <prefix>/<filename>.pmtiles]
  > S3 endpoint URL: [Press Enter for AWS S3; for Cloudflare R2: https://<ACCOUNT_ID>.r2.cloudflarestorage.com]
  > AWS Access Key ID: <Your_Access_Key_ID (required)>
  > AWS Secret Access Key: <Your_Secret_Access_Key (required)>
  > AWS Region: [AWS region, or auto for Cloudflare R2]
  ```

#### mbtiles2s3
- Upload a MBTiles file to Amazon S3 or S3-compatible storage (e.g. Cloudflare R2).
  For AWS S3, install AWS CLI and run `aws configure` first, or pass credentials via flags.
  ``` bash 
  > mbtiles2s3 <input file> <s3://bucket/prefix> -p
  > mbtiles2s3 <input file> <s3://bucket/prefix> -p --endpoint-url <R2_ENDPOINT> --access-key-id <KEY> --secret-access-key <SECRET> --region auto
  ```
  Ex (AWS): `> mbtiles2s3 tiles.mbtiles s3://mybucket/tiles -p`  
  Ex (Cloudflare R2): `> mbtiles2s3 tiles.mbtiles s3://vietnam/vn -p --endpoint-url https://<ACCOUNT_ID>.r2.cloudflarestorage.com --access-key-id <R2_KEY> --secret-access-key <R2_SECRET> --region auto`
- Install aws cli on Ubuntu:
  ``` bash 
  sudo apt update
  sudo apt install curl unzip -y
  curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
  unzip awscliv2.zip
  sudo ./aws/install
  ```
  Verify aws cli installation:
  ``` bash 
  aws --version
  ```
- Configure aws cli:
  ``` bash 
  aws configure
  ```
  Input AWS Access Key ID and AWS Secret Access Key
  ``` bash 
  AWS Access Key ID [None]: AKIAxxxxxxxxxxxxxxxx
  AWS Secret Access Key [None]: wJalrxxxxxxxxxxxxxxxxxxxxxxxxxx
  Default region name [None]:
  Default output format [None]:
  ```
  Check aws configuration by listing your S3 buckets:
  ``` bash 
  aws s3 ls
  ```

#### mbtiles2pbf
- Extract a tile from MBTiles to PBF 
  ``` bash 
    > mbtiles2pbf  <input file> -z <zoom level> -x <tile column> -y <tile row> -o <output file>
  ```
  Ex: `> mbtiles2pbf  tiles.mbtils -z 2 -x 1 -y 2 -o pbf_212.pbf`

#### pbfinfo
- Show pbf metadata info
  ``` bash 
    > pbfinfo <input file>
  ```
  Ex: `> pbfinfo pbf_file.pbf`

#### pbf2geojson
- Convert tile data from a BBF file or MBTiles file to GeoJSON 
  ``` bash 
    > pbf2geojson <input pbf or MBTiles > -o <output file> -z <tile zoom level, default is 0> - x <tile column, default is 0> -y <tile row, default is 0>  -flipy [TMS <--> XYZ tiling scheme (optional): 1 or 0, default is 0] 
  ```
  Ex: `> pbf2geojson tiles.mbtiles -o geojson_file.geojson -z 2 -x 1 -y 2`  
      `> pbf2geojson pbf_file.pbf`
 
#### flipy
- Convert TMS <--> XYZ tiling scheme for a tiles folder
  ``` bash 
    > flipy  <input folder> -o <output folder>
  ```
  Ex: `> flipy  input_folder -o output_folder`

#### mbtiles2pmtiles
- Convert Convert MBTiles to PMTiles
  ``` bash 
    > flipy  <input MBTiles> -o <output PMTiles> -z <max zoom level>
  ```
  Ex: `> mbtiles2pmtiles  mbtiles_file.mbtiles -o pmtiles_file.pmtiles -z 6`

#### mbtilessplit
- Split an MBTiles file by selected layers
  ``` bash 
    > mbtilessplit  <input file> -o <output file> -l <list of layer names to be splitted>
  ```
  Ex: `> mbtilessplit  input_file.mbtiles -o splitted_file.mbtiles -l water`
      (mbtilessplit also save remaining mbtiles layers to {input file}_remained.mbtiles)

#### mbtilesmerge
- Merge multiple MBTiles files into a single MBTiles file
  ``` bash 
    > mbtilesmerge  <input file list> -o <output file> -l <list of layer names to be splitted>
  ```
  Ex: `> mbtilesmerge  file_1.mbtiles file_2.mbtiles -o merged.mbtiles`

#### mbtilescompress
- Compress MBTiles file with GZIP
  ``` bash 
    > mbtilescompress  <input file> -o <output file>
  ```
  Ex: `> mbtilescompress  mbtiles_file.mbtiles -o compressed.mbtiles`

#### mbtilesdecompress
- Decompress MBTiles file (either being compressed with GZIP or ZLIB)
  ``` bash 
    > mbtilesdecompress  <input file> -o <output file>
  ```
  Ex: `> mbtilesdecompress  mbtiles_file.mbtiles -o decompressed.mbtiles`

#### mbtilesfixmeta
- Create or update metadata for an existing MBTiles file.
  ``` bash 
    > mbtilesfixmeta <input file>
  ```
  Ex: `> mbtilesfixmeta mbtiles_file.mbtiles`

### MBTILES Server Utilities:
#### servefolder
- Serve a raster tiles or vector tiles for the current folder, so clients can access to the tiles server via, for ex. htttp://localhost/8000/tiles/{z}/{x}/{y}.pbf.
  ``` bash 
    > servefolder
  ```

#### servembtiles
- Serve raster tiles for the input MBTiles file, so clients can access to the tiles server via, for ex. htttp://localhost/8000/rastertiles/z/x/y.png.
  ``` bash 
    > servembtiles --serve -p <port> -f <input file>
  ```
#### servevectormbtiles
- Serve vector tiles for the input MBTiles file, so clients can access to the tiles server via, for ex. htttp://localhost/8000/vectortiles/z/x/y.pbf.
  ``` bash 
    > servevectormbtiles --serve -p <port> -f <input file>
  ```
#### servepostgis
- Serve MVT tiles from a PostgreSQL/PostGIS database, so clients can access to the tiles server via, for ex. htttp://localhost/8000/mvt/z/x/y.pbf.
  ``` bash 
    > servepostgis -config <YAML configuration file> 
  ```
#### servepmtiles
- Serve vector tiles for an pmtiles file htttp://localhost/8000/pmtiles/z/x/y.pbf.
  ``` bash 
    > servepmtiles  <PMTiles file> -port <port number> -host <host IP, default is localhost>
  ```
### Other Utilities:
#### pmtilesinfo
- Show PMTiles metadata.
  ``` bash 
    > pmtilesinfo <mbtiles file> Z [zoom level] X [tile column] Y [tile row]
  ```
#### pmtiles2folder
- Convert PMTiles file to folder
    ``` bash 
    > pmtiles2folder  <input file> -o <output_folder>
    ```
#### pmtiles2mbtiles
- Convert PMTiles file to MBTiles file
    ``` bash 
    > pmtiles2mbtiles  <input PMTiles> -o <output MBTiles>
    ```
#### h3parquet2pmtiles
- Convert a Parquet file of H3 cells to PMTiles. The `h3` column is decoded to a hexagon only to match each row against XYZ tiles; the output stores attributes (`h3`, `population`, …) and does **not** write geometry.
    ``` bash
    > h3parquet2pmtiles <input.parquet> -o [output.pmtiles] -z [maxzoom, default 5] --minzoom [default 0] --h3 [h3 column] --layer [layer name]
    ```
  Ex: `> h3parquet2pmtiles h3_4.parquet -o h3_4.pmtiles -z 8`
