"""Storage service — local filesystem for dev, S3/Cloudinary for production."""
import logging
import os
from core.config import settings

logger = logging.getLogger(__name__)
os.makedirs(settings.LOCAL_STORAGE_PATH, exist_ok=True)


class StorageService:
    """Async storage abstraction over local/S3/Cloudinary."""

    async def upload(self, content: bytes, key: str, content_type: str = "audio/wav") -> str:
        if settings.STORAGE_BACKEND == "s3":
            return await self._upload_s3(content, key, content_type)
        elif settings.STORAGE_BACKEND == "cloudinary":
            return await self._upload_cloudinary(content, key)
        return await self._upload_local(content, key)

    async def download(self, url_or_key: str) -> bytes:
        if settings.STORAGE_BACKEND == "s3":
            return await self._download_s3(url_or_key)
        return await self._download_local(url_or_key)

    async def delete(self, url_or_key: str):
        if settings.STORAGE_BACKEND == "local":
            await self._delete_local(url_or_key)
        # For S3/Cloudinary, implement as needed

    # ── Local filesystem ──────────────────────────────────────────────────────

    async def _upload_local(self, content: bytes, key: str) -> str:
        path = os.path.join(settings.LOCAL_STORAGE_PATH, key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(content)
        return f"/storage/{key}"

    async def _download_local(self, url_or_key: str) -> bytes:
        # Strip leading /storage/
        key = url_or_key.lstrip("/storage/")
        path = os.path.join(settings.LOCAL_STORAGE_PATH, key)
        with open(path, "rb") as f:
            return f.read()

    async def _delete_local(self, url_or_key: str):
        key = url_or_key.lstrip("/storage/")
        path = os.path.join(settings.LOCAL_STORAGE_PATH, key)
        if os.path.exists(path):
            os.unlink(path)

    # ── AWS S3 ────────────────────────────────────────────────────────────────

    async def _upload_s3(self, content: bytes, key: str, content_type: str) -> str:
        try:
            import boto3
            s3 = boto3.client(
                "s3",
                region_name=settings.AWS_REGION,
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            )
            s3.put_object(Bucket=settings.S3_BUCKET, Key=key, Body=content, ContentType=content_type)
            cdn = settings.S3_CDN_URL or f"https://{settings.S3_BUCKET}.s3.{settings.AWS_REGION}.amazonaws.com"
            return f"{cdn}/{key}"
        except Exception as e:
            logger.error(f"S3 upload failed: {e}")
            return await self._upload_local(content, key)

    async def _download_s3(self, key: str) -> bytes:
        import boto3
        s3 = boto3.client("s3", region_name=settings.AWS_REGION)
        obj = s3.get_object(Bucket=settings.S3_BUCKET, Key=key)
        return obj["Body"].read()

    # ── Cloudinary ────────────────────────────────────────────────────────────

    async def _upload_cloudinary(self, content: bytes, key: str) -> str:
        try:
            import cloudinary
            import cloudinary.uploader
            cloudinary.config(
                cloud_name=settings.CLOUDINARY_CLOUD_NAME,
                api_key=settings.CLOUDINARY_API_KEY,
                api_secret=settings.CLOUDINARY_API_SECRET,
            )
            result = cloudinary.uploader.upload(content, public_id=key, resource_type="video")
            return result["secure_url"]
        except Exception as e:
            logger.error(f"Cloudinary upload failed: {e}")
            return await self._upload_local(content, key)


storage_service = StorageService()
