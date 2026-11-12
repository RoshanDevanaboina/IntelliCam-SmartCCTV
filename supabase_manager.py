"""
CC TV — Supabase Cloud Storage & Sync Manager
Handles uploading snapshots and video recordings to Supabase Storage,
generating public/signed URLs for notifications and web playback.
"""
import os
import logging
from typing import Optional, Union

logger = logging.getLogger(__name__)

try:
    from supabase import create_client, Client
    HAS_SUPABASE = True
except ImportError:
    HAS_SUPABASE = False
    Client = None


class SupabaseManager:
    """Manages cloud storage and remote assets with Supabase."""

    def __init__(self, url: str = "", key: str = "",
                 snapshot_bucket: str = "cctv-snapshots",
                 recording_bucket: str = "cctv-recordings"):
        self.url = url
        self.key = key
        self.snapshot_bucket = snapshot_bucket
        self.recording_bucket = recording_bucket
        self.client: Optional[Client] = None
        self.enabled = False

        if HAS_SUPABASE and self.url and self.key:
            try:
                self.client = create_client(self.url, self.key)
                self.enabled = True
                logger.info(f"Supabase client initialized for: {self.url}")
                self._ensure_buckets()
            except Exception as e:
                logger.warning(f"Could not connect to Supabase: {e}")
                self.enabled = False
        else:
            if not HAS_SUPABASE:
                logger.debug("supabase-py library not installed.")
            else:
                logger.debug("Supabase URL or Key not configured; using local storage.")

    def _ensure_buckets(self):
        """Ensure storage buckets exist and are public."""
        if not self.enabled or not self.client:
            return
        try:
            existing = [b.name for b in self.client.storage.list_buckets()]
            for bucket_name in [self.snapshot_bucket, self.recording_bucket]:
                if bucket_name not in existing:
                    try:
                        self.client.storage.create_bucket(bucket_name, options={"public": True})
                        logger.info(f"Created Supabase storage bucket: {bucket_name}")
                    except Exception as e:
                        logger.debug(f"Bucket {bucket_name} check/creation notice: {e}")
        except Exception as e:
            logger.debug(f"Could not list Supabase buckets: {e}")

    def upload_snapshot(self, data_or_path: Union[bytes, str], remote_filename: str) -> Optional[str]:
        """
        Uploads a JPEG snapshot to Supabase Storage.
        Returns the public URL if successful, otherwise None.
        """
        if not self.enabled or not self.client:
            return None

        try:
            if isinstance(data_or_path, str):
                with open(data_or_path, "rb") as f:
                    file_bytes = f.read()
            else:
                file_bytes = data_or_path

            remote_path = remote_filename.replace("\\", "/").lstrip("/")
            
            # Upload (upsert to allow overwrite if re-triggered)
            self.client.storage.from_(self.snapshot_bucket).upload(
                path=remote_path,
                file=file_bytes,
                file_options={"content-type": "image/jpeg", "upsert": "true"}
            )

            # Get public URL
            public_url = self.client.storage.from_(self.snapshot_bucket).get_public_url(remote_path)
            logger.info(f"Uploaded snapshot to Supabase: {public_url}")
            return public_url

        except Exception as e:
            logger.error(f"Failed to upload snapshot to Supabase: {e}")
            return None

    def upload_recording(self, local_path: str, remote_filename: str) -> Optional[str]:
        """
        Uploads an MP4 video clip to Supabase Storage.
        Returns the public URL if successful, otherwise None.
        """
        if not self.enabled or not self.client:
            return None

        if not os.path.exists(local_path):
            logger.warning(f"Recording file not found for upload: {local_path}")
            return None

        try:
            with open(local_path, "rb") as f:
                file_bytes = f.read()

            remote_path = remote_filename.replace("\\", "/").lstrip("/")

            self.client.storage.from_(self.recording_bucket).upload(
                path=remote_path,
                file=file_bytes,
                file_options={"content-type": "video/mp4", "upsert": "true"}
            )

            public_url = self.client.storage.from_(self.recording_bucket).get_public_url(remote_path)
            logger.info(f"Uploaded recording to Supabase: {public_url}")
            return public_url

        except Exception as e:
            logger.error(f"Failed to upload recording to Supabase: {e}")
            return None
