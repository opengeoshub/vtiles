#!/usr/bin/env python3
# Upload MBTiles to Amazon S3 or S3-compatible storage (e.g. Cloudflare R2).
# Examples:
#   mbtiles2s3 tiles.mbtiles s3://mybucket/prefix -p
#   mbtiles2s3 tiles.mbtiles s3://vietnam/vn -p \
#     --endpoint-url https://<ACCOUNT_ID>.r2.cloudflarestorage.com \
#     --access-key-id <R2_KEY> --secret-access-key <R2_SECRET> --region auto

import json
import logging
import os
import sqlite3
from functools import partial
from multiprocessing.pool import ThreadPool
from urllib.parse import urlparse

import click

from vtiles.mbtiles.s3client import create_s3_client

upload_progress_interval = 100
tile_count = 0
upload_count = 0


class MBTilesGenerator(object):
    """Generator that returns tiles from an mbtiles file"""

    def __init__(self, mbtiles):
        super(MBTilesGenerator, self).__init__()
        self.db = sqlite3.connect(mbtiles)
        self.cursor = self.db.cursor()
        self.cursor.execute(
            "SELECT zoom_level, tile_column, tile_row, tile_data FROM tiles order by zoom_level"
        )

    def len(self):
        c = self.db.cursor()
        c.execute("SELECT count(1) from tiles")
        return c.fetchone()[0]

    def __iter__(self):
        return self

    def __next__(self):
        row = self.cursor.fetchone()
        if row == None:
            raise StopIteration()
        zoom, x, y, tile = row
        y = ((1 << zoom) - y) - 1
        return zoom, x, y, tile


def get_tile_json(mbtiles, bucket, key_template, public_base_url=None):
    db = sqlite3.connect(mbtiles)
    cursor = db.cursor()
    cursor.execute("SELECT name, value FROM metadata")
    if public_base_url:
        tiles_url = "{}/{}/{}".format(public_base_url.rstrip("/"), bucket, key_template)
    else:
        tiles_url = "https://s3.amazonaws.com/{}/{}".format(bucket, key_template)
    tilejson = {
        "tilejson": "2.2.0",
        "scheme": "xyz",
        "tiles": [tiles_url],
    }
    for key, value in cursor.fetchall():
        if key == "json":
            data = json.loads(value)
            tilejson.update(data)
        else:
            if key in ("center", "bounds"):
                value = [float(s) for s in value.split(",")]
            elif key in ("minzoom", "maxzoom"):
                value = int(value)
            tilejson[key] = value
    return tilejson


def upload_tile(
    s3, bucket, key_template, headers, tile_stuff, progress=True, retries=0
):
    try:
        zoom, x, y, tile = tile_stuff
        put_args = {
            "Body": tile,
            "Bucket": bucket,
            "Key": key_template.format(z=zoom, x=x, y=y),
            "ContentType": headers.get("Content-Type", ""),
        }
        if headers.get("Content-Encoding"):
            put_args["ContentEncoding"] = headers["Content-Encoding"]
        if headers.get("Cache-Control"):
            put_args["CacheControl"] = headers["Cache-Control"]
        s3.put_object(**put_args)
        global upload_count
        upload_count += 1
        if progress and upload_count % upload_progress_interval == 0:
            print("%i/%i" % (upload_count, tile_count))
    except Exception as e:
        logging.error(str(e))
        if retries < 2:
            upload_tile(
                s3,
                bucket,
                key_template,
                headers,
                tile_stuff,
                progress=progress,
                retries=retries + 1,
            )
        else:
            raise Exception("Too Many upload failures")


@click.command()
@click.argument("mbtiles", type=click.Path(exists=True), required=True)
@click.argument("s3_url", required=True)
@click.option("--threads", default=10, help="Number of simultaneous uploads")
@click.option("--extension", default=".pbf", help="File extension for tiles")
@click.option("--header", "-h", multiple=True, help="Additional headers")
@click.option(
    "--progress", "-p", default=False, is_flag=True, help="Show upload progress"
)
@click.option("--debug", "-d", default=False, help="Debug level logging", is_flag=True)
@click.option(
    "--endpoint-url",
    default=None,
    help="S3-compatible endpoint URL (for Cloudflare R2: https://<ACCOUNT_ID>.r2.cloudflarestorage.com)",
)
@click.option("--region", default=None, help="AWS region (use auto for Cloudflare R2)")
@click.option("--access-key-id", default=None, help="Access key ID (R2 or AWS)")
@click.option("--secret-access-key", default=None, help="Secret access key (R2 or AWS)")
@click.option(
    "--public-base-url",
    default=None,
    help="Public base URL for tile.json (e.g. https://tiles.example.com). Defaults to endpoint URL or AWS S3.",
)
def main(
    mbtiles,
    s3_url,
    threads,
    extension,
    header,
    progress,
    debug,
    endpoint_url,
    region,
    access_key_id,
    secret_access_key,
    public_base_url,
):
    """Upload tiles from an MBTiles file to S3 or S3-compatible storage (e.g. Cloudflare R2).

    \b
    PARAMS:
        mbtiles: Path to an MBTiles file
        s3_url: url to an s3 bucket to upload tiles to, e.g. s3://bucket/prefix
    """
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)
    logging.getLogger("botocore.credentials").setLevel(logging.getLevelName("ERROR"))
    logging.getLogger(
        "botocore.vendored.requests.packages.urllib3.connectionpool"
    ).setLevel(logging.getLevelName("ERROR"))
    logging.getLogger("urllib3.connectionpool").setLevel(logging.getLevelName("ERROR"))

    base_url = urlparse(s3_url)
    bucket = base_url.netloc
    key_prefix = base_url.path.lstrip("/")

    if endpoint_url:
        logging.info(f"Using endpoint: {endpoint_url.strip().rstrip('/')}")

    s3 = create_s3_client(
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        endpoint_url=endpoint_url,
        aws_region=region,
        max_pool_connections=max(threads, 10),
    )

    try:
        s3.head_bucket(Bucket=bucket)
    except Exception as e:
        if endpoint_url and "SignatureDoesNotMatch" in str(e):
            raise click.ClickException(
                "SignatureDoesNotMatch: check R2 API token keys, endpoint "
                "https://<ACCOUNT_ID>.r2.cloudflarestorage.com, and --region auto."
            ) from e
        raise click.ClickException(f"Cannot access bucket '{bucket}': {e}") from e

    headers = {}
    if header is not None:
        for h in header:
            k, v = h.split(":")
            if k not in ("Cache-Control", "Content-Type", "Content-Encoding"):
                raise Exception("Unsupported header")
            headers[k] = v

    if extension == ".pbf" or extension == ".mvt":
        headers.update(
            {
                "Content-Encoding": "gzip",
                "Content-Type": "application/x-protobuf",
            }
        )
    elif extension == ".webp":
        headers.update({"Content-Type": "image/webp"})
    elif extension == ".png":
        headers.update({"Content-Type": "image/png"})
    elif extension == ".jpg" or extension == ".jpeg":
        headers.update({"Content-Type": "image/jpeg"})

    tiles = MBTilesGenerator(mbtiles)
    global tile_count
    tile_count = tiles.len()

    key_template = key_prefix + "/{z}/{x}/{y}" + extension
    logging.info(f"uploading tiles from {mbtiles} to s3://{bucket}/{key_template}")
    pool = ThreadPool(threads)
    func = partial(upload_tile, s3, bucket, key_template, headers, progress=progress)
    pool.map(func, tiles)

    tilejson_key = "{}/tile.json".format(key_prefix.strip("/"))
    logging.info(f"uploading tile.json to s3://{bucket}/{tilejson_key}")
    tile_public_base = public_base_url or endpoint_url
    tilejson_data = get_tile_json(mbtiles, bucket, key_template, tile_public_base)
    s3.put_object(
        Body=json.dumps(tilejson_data, indent=4, sort_keys=True),
        Bucket=bucket,
        Key=tilejson_key,
        ContentType="application/json",
    )
    logging.info("Upload done!")


if __name__ == "__main__":
    main()
