import boto3
import os
import uuid

# =============================
# ENVIRONMENT VARIABLES
# =============================

AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION")
AWS_BUCKET_NAME = os.getenv("AWS_BUCKET_NAME")

# =============================
# S3 CLIENT
# =============================

s3_client = boto3.client(
    "s3",
    region_name=AWS_REGION,
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY
)

# =============================
# UPLOAD FILE TO S3
# =============================

def upload_file_to_s3(file, project_id: int, folder: str):
    """
    Uploads file to S3 under:
    projects/{project_id}/{folder}/{unique_filename}
    """

    file_extension = file.filename.split(".")[-1]
    unique_filename = f"{uuid.uuid4()}.{file_extension}"

    s3_key = f"projects/{project_id}/{folder}/{unique_filename}"

    s3_client.upload_fileobj(
        file.file,
        AWS_BUCKET_NAME,
        s3_key,
        ExtraArgs={
            "ContentType": file.content_type
        }
    )

    # Store the S3 URL (even though we wonât use public access)
    file_url = f"https://{AWS_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{s3_key}"

    return file_url

# =============================
# DOWNLOAD FILE FROM S3
# =============================

def download_file_from_s3(file_url: str, temp_file):
    """
    Downloads a file from S3 using its URL and writes to temp file.
    """

    # Extract key from full URL
    file_key = file_url.split(".amazonaws.com/")[-1]

    s3_client.download_fileobj(
        AWS_BUCKET_NAME,
        file_key,
        temp_file
    )
