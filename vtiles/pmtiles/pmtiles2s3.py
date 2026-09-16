"""Upload a PMTiles file to Amazon S3 or S3-compatible storage (e.g. Cloudflare R2)."""

import argparse
import logging
import os

from boto3.s3.transfer import TransferConfig
from tqdm import tqdm

from vtiles.mbtiles.s3client import create_s3_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PMTILES_CONTENT_TYPE = "application/vnd.pmtiles"
# Multipart parts of 64 MiB work well for large PMTiles on R2/S3.
DEFAULT_MULTIPART_THRESHOLD = 64 * 1024 * 1024
DEFAULT_MULTIPART_CHUNKSIZE = 64 * 1024 * 1024


class ProgressPercentage:
    def __init__(self, filename, pbar):
        self._filename = filename
        self._size = float(os.path.getsize(filename))
        self._seen = 0
        self._pbar = pbar

    def __call__(self, bytes_amount):
        self._seen += bytes_amount
        self._pbar.n = min(self._seen, int(self._size))
        self._pbar.refresh()


def build_s3_key(s3_prefix, filename):
    name = os.path.basename(filename)
    prefix = (s3_prefix or "").strip().strip("/")
    if not prefix:
        return name
    return f"{prefix}/{name}"


def pmtiles2s3(
    input_file,
    bucket_name="",
    s3_prefix="",
    aws_access_key_id=None,
    aws_secret_access_key=None,
    aws_region=None,
    endpoint_url=None,
    verbose=False,
):
    file_size = os.path.getsize(input_file)
    s3_key = build_s3_key(s3_prefix, input_file)

    try:
        logging.info("Creating a connection to S3")
        if endpoint_url:
            logging.info(f'Using endpoint: {endpoint_url.strip().rstrip("/")}')
        s3 = create_s3_client(
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            endpoint_url=endpoint_url,
            aws_region=aws_region,
            max_pool_connections=10,
        )
        s3.head_bucket(Bucket=bucket_name)
    except Exception as e:
        logging.error(f"Failed to connect to S3 bucket '{bucket_name}': {e}")
        if endpoint_url and "SignatureDoesNotMatch" in str(e):
            logging.error(
                "SignatureDoesNotMatch usually means wrong R2 credentials or endpoint. "
                "Use R2 API token keys (not AWS keys), endpoint "
                "https://<ACCOUNT_ID>.r2.cloudflarestorage.com, and region auto."
            )
        return False

    transfer_config = TransferConfig(
        multipart_threshold=DEFAULT_MULTIPART_THRESHOLD,
        multipart_chunksize=DEFAULT_MULTIPART_CHUNKSIZE,
        max_concurrency=4,
        use_threads=True,
    )
    extra_args = {"ContentType": PMTILES_CONTENT_TYPE}

    try:
        size_mb = file_size / (1024 * 1024)
        logging.info(
            f"Uploading {input_file} ({size_mb:.1f} MiB) to "
            f"s3://{bucket_name}/{s3_key}. Press Ctrl+C to cancel"
        )
        with tqdm(
            total=file_size,
            unit="B",
            unit_scale=True,
            unit_divisor=1024,
            desc="Uploading",
            disable=not verbose,
        ) as pbar:
            s3.upload_file(
                input_file,
                bucket_name,
                s3_key,
                ExtraArgs=extra_args,
                Config=transfer_config,
                Callback=ProgressPercentage(input_file, pbar) if verbose else None,
            )
        logging.info(f"Upload done: s3://{bucket_name}/{s3_key}")
        return True
    except Exception as e:
        logging.error(f"Error uploading {input_file} to {s3_key}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Upload a PMTiles file to S3 or S3-compatible storage "
            "(e.g. Cloudflare R2)."
        )
    )
    parser.add_argument("input", type=str, help="Path to the .pmtiles file to upload.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show progress bar")
    args = parser.parse_args()

    input_file = args.input
    if not os.path.exists(input_file) or not os.path.isfile(input_file):
        logging.error(
            "Input file does not exist or is invalid. Please recheck and provide a correct one."
        )
        raise SystemExit(1)

    if not input_file.lower().endswith(".pmtiles"):
        logging.error("Input must be a .pmtiles file.")
        raise SystemExit(1)

    input_file_abspath = os.path.abspath(input_file)

    logging.info("### Input S3 parameters:")
    s3_bucket_name = input("S3 Bucket name: ").strip()
    while not s3_bucket_name:
        logging.error("S3 Bucket name is required.")
        s3_bucket_name = input("S3 Bucket name: ").strip()

    s3_prefix = input(
        f"S3 prefix (Press Enter to upload to the bucket {s3_bucket_name} root folder): "
    ).strip()

    endpoint_url = input(
        "S3 endpoint URL (Press Enter for AWS S3; for Cloudflare R2 use "
        "https://<ACCOUNT_ID>.r2.cloudflarestorage.com): "
    ).strip()
    if not endpoint_url:
        endpoint_url = None

    aws_access_key_id = input("AWS Access Key ID: ").strip()
    while not aws_access_key_id:
        aws_access_key_id = input(
            "AWS Access Key ID is required. Please input AWS Access Key ID: "
        ).strip()

    aws_secret_access_key = input("AWS Secret Access Key: ").strip()
    while not aws_secret_access_key:
        aws_secret_access_key = input(
            "AWS Secret Access Key is required. Please input AWS Secret Access Key: "
        ).strip()

    aws_region = input(
        "AWS region (Press Enter for default; for Cloudflare R2 use auto): "
    ).strip()
    if not aws_region:
        aws_region = "auto" if endpoint_url else None

    ok = pmtiles2s3(
        input_file_abspath,
        s3_bucket_name,
        s3_prefix,
        aws_access_key_id,
        aws_secret_access_key,
        aws_region,
        endpoint_url,
        args.verbose,
    )
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
