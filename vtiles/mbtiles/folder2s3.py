import os
import sys
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor
import multiprocessing
import argparse
import logging

from vtiles.mbtiles.s3client import create_s3_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
s3 = None

def upload_file(bucket_name, local_file_path, s3_key, content_type=None, content_encoding=None):
    try:
        put_args = {
            'Bucket': bucket_name,
            'Key': s3_key,
        }
        if content_type:
            put_args['ContentType'] = content_type
        if content_encoding:
            put_args['ContentEncoding'] = content_encoding
        with open(local_file_path, 'rb') as f:
            put_args['Body'] = f.read()
        s3.put_object(**put_args)
        return True
    except Exception as e:
        logging.error(f"Error uploading {local_file_path} to {s3_key}: {e}")
        return False

def upload_files(bucket_name, input_folder, s3_prefix='', content_type=None, content_encoding=None, verbose=False, max_workers=None):
    total_files = sum(len(files) for _, _, files in os.walk(input_folder))
    if max_workers is None:
        max_workers = min(multiprocessing.cpu_count() * 2, 10)

    with tqdm(total=total_files, desc="Uploading", unit="files ", disable=not verbose) as pbar:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for root, _, files in os.walk(input_folder):
                for file in files:
                    local_file_path = os.path.join(root, file)
                    s3_key = os.path.relpath(local_file_path, input_folder)
                    s3_key = os.path.join(s3_prefix, s3_key).replace('\\', '/')  # for Windows compatibility
                    future = executor.submit(upload_file, bucket_name, local_file_path, s3_key, content_type, content_encoding)
                    future.add_done_callback(lambda p: pbar.update())
                    futures.append(future)
            # Wait for all uploads to complete
            for future in futures:
                future.result()

def folder2s3(input_folder, format='', bucket_name='', s3_prefix='', aws_access_key_id=None, aws_secret_access_key=None, aws_region=None, endpoint_url=None, verbose=False):
    max_workers = min(multiprocessing.cpu_count() * 2, 10)

    try:
        logging.info('Creating a connection to S3')
        if endpoint_url:
            logging.info(f'Using endpoint: {endpoint_url.strip().rstrip("/")}')
        global s3
        s3 = create_s3_client(
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            endpoint_url=endpoint_url,
            aws_region=aws_region,
            max_pool_connections=max_workers,
        )
        s3.head_bucket(Bucket=bucket_name)
    except Exception as e:
        logging.error(f"Failed to connect to S3 bucket '{bucket_name}': {e}")
        if endpoint_url and 'SignatureDoesNotMatch' in str(e):
            logging.error(
                'SignatureDoesNotMatch usually means wrong R2 credentials or endpoint. '
                'Use R2 API token keys (not AWS keys), endpoint '
                'https://<ACCOUNT_ID>.r2.cloudflarestorage.com, and region auto.'
            )
        return

    try:
        logging.info(f'Uploading folder {input_folder} to S3 bucket: {bucket_name}. Press Ctrl+C to cancel')
        if format == 'pbf' or format == 'mvt':
            upload_files(bucket_name, input_folder, s3_prefix, 'application/x-protobuf', 'gzip', verbose, max_workers)
        else:
            upload_files(bucket_name, input_folder, s3_prefix, verbose=verbose, max_workers=max_workers)
        logging.info('Uploading folder to S3 done!')
    except Exception as e:
        logging.error(f"Error uploading folder to S3: {e}")
        return

def main():
    parser = argparse.ArgumentParser(description='Upload a tiles folder to S3 or S3-compatible storage (e.g. Cloudflare R2).')
    parser.add_argument('input', type=str, help='The tiles folder to upload.')
    parser.add_argument('-format', type=str, required=True, choices=['pbf', 'mvt', 'png', 'jpg', 'jpeg', 'webp'], help='format of the files to upload.')
    parser.add_argument('-v', '--verbose', action='store_true', help='Show progress bar')
    args = parser.parse_args()

    input_folder = args.input
    format = args.format

    if not os.path.exists(input_folder) or not os.path.isdir(input_folder):
        logging.error('Input folder does not exist or is invalid. Please recheck and provide a correct one.')
        exit()

    input_folder_abspath = os.path.abspath(input_folder)

    logging.info('### Input S3 parameters:')
    s3_bucket_name = input('S3 Bucket name: ')
    while not s3_bucket_name:
        logging.error('S3 Bucket name is required.')
        s3_bucket_name = input('S3 Bucket name: ')

    s3_prefix = input(f'S3 prefix (Press Enter to upload to the bucket {s3_bucket_name} root folder): ')
    if not s3_prefix:
        s3_prefix = ''

    endpoint_url = input('S3 endpoint URL (Press Enter for AWS S3; for Cloudflare R2 use https://<ACCOUNT_ID>.r2.cloudflarestorage.com): ').strip()
    if not endpoint_url:
        endpoint_url = None

    aws_access_key_id = input('AWS Access Key ID: ')
    while not aws_access_key_id:
        aws_access_key_id = input('AWS Access Key ID is required. Please input AWS Access Key ID: ')

    aws_secret_access_key = input('AWS Secret Access Key: ')
    while not aws_secret_access_key:
        aws_secret_access_key = input('AWS Secret Access Key is required. Please input AWS Secret Access Key: ')

    aws_region = input('AWS region (Press Enter for default; for Cloudflare R2 use auto): ').strip()
    if not aws_region:
        aws_region = 'auto' if endpoint_url else None

    folder2s3(input_folder_abspath, format, s3_bucket_name, s3_prefix, aws_access_key_id, aws_secret_access_key, aws_region, endpoint_url, args.verbose)

if __name__ == "__main__":
    main()
