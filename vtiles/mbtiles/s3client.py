"""Shared boto3 S3 client helpers for AWS S3 and S3-compatible storage (e.g. Cloudflare R2)."""

import boto3
from botocore.config import Config


def s3_client_config(max_pool_connections=10):
    """Build a botocore Config compatible with Cloudflare R2.

    boto3 >= 1.36 enables CRC32 checksums by default, which R2 rejects and can
    surface as SignatureDoesNotMatch. See:
    https://developers.cloudflare.com/r2/examples/aws/boto3/
    """
    kwargs = {
        "max_pool_connections": max_pool_connections,
        "s3": {"addressing_style": "path"},
    }
    try:
        return Config(
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
            **kwargs,
        )
    except TypeError:
        return Config(**kwargs)


def create_s3_client(
    *,
    aws_access_key_id,
    aws_secret_access_key,
    endpoint_url=None,
    aws_region=None,
    max_pool_connections=10,
):
    """Create a boto3 S3 client for AWS S3 or S3-compatible endpoints."""
    client_kwargs = {
        "service_name": "s3",
        "aws_access_key_id": aws_access_key_id.strip() if aws_access_key_id else None,
        "aws_secret_access_key": aws_secret_access_key.strip()
        if aws_secret_access_key
        else None,
        "config": s3_client_config(max_pool_connections),
    }
    if endpoint_url:
        client_kwargs["endpoint_url"] = endpoint_url.strip().rstrip("/")
        if not aws_region:
            client_kwargs["region_name"] = "auto"
    if aws_region:
        client_kwargs["region_name"] = aws_region.strip()
    return boto3.client(**client_kwargs)
