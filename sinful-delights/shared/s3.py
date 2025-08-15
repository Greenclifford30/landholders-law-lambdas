"""
S3 utilities for Sinful Delights API
"""
import boto3
import os
from typing import Dict, Tuple
from botocore.exceptions import ClientError
from .errors import InternalError


# Initialize S3 client
s3_client = boto3.client('s3')


def get_bucket_name() -> str:
    """Get S3 bucket name from environment"""
    bucket_name = os.environ.get('BUCKET_NAME')
    if not bucket_name:
        raise InternalError("BUCKET_NAME environment variable not set")
    return bucket_name


def get_cdn_base_url() -> str:
    """Get CDN base URL from environment"""
    cdn_url = os.environ.get('CDN_BASE_URL', '')
    return cdn_url


def generate_presigned_upload_url(file_name: str, content_type: str, expiration: int = 3600) -> Tuple[str, str]:
    """
    Generate a presigned URL for uploading a file to S3.
    Returns tuple of (upload_url, final_file_url).
    """
    bucket_name = get_bucket_name()
    cdn_base_url = get_cdn_base_url()
    
    # Generate unique key for the file (could add timestamp or UUID prefix)
    object_key = f"images/{file_name}"
    
    try:
        # Generate presigned URL for upload
        upload_url = s3_client.generate_presigned_url(
            'put_object',
            Params={
                'Bucket': bucket_name,
                'Key': object_key,
                'ContentType': content_type
            },
            ExpiresIn=expiration
        )
        
        # Generate final URL for accessing the file
        if cdn_base_url:
            file_url = f"{cdn_base_url}/{object_key}"
        else:
            file_url = f"https://{bucket_name}.s3.amazonaws.com/{object_key}"
        
        return upload_url, file_url
        
    except ClientError as e:
        raise InternalError(f"Failed to generate presigned URL: {str(e)}")


def validate_content_type(content_type: str) -> bool:
    """
    Validate that the content type is allowed for image uploads.
    """
    allowed_types = [
        'image/jpeg',
        'image/jpg',
        'image/png',
        'image/gif',
        'image/webp'
    ]
    return content_type.lower() in allowed_types


def validate_file_name(file_name: str) -> bool:
    """
    Validate file name for security and format.
    """
    if not file_name or len(file_name) > 255:
        return False
    
    # Check for dangerous characters
    dangerous_chars = ['..', '/', '\\', '<', '>', ':', '"', '|', '?', '*']
    for char in dangerous_chars:
        if char in file_name:
            return False
    
    # Check file extension
    allowed_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp']
    file_extension = file_name.lower().split('.')[-1] if '.' in file_name else ''
    return f'.{file_extension}' in allowed_extensions