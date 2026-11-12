"""
CC TV — Event Recorder
Handles saving snapshots and video clips when detection events occur.
Optionally uploads assets directly to Supabase Storage for cloud access.
"""
import cv2
import os
import time
import threading
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class EventRecorder:
    """Records snapshots and video clips for detection events."""

    def __init__(self, camera_manager, config, supabase_manager=None):
        self.camera_manager = camera_manager
        self.config = config
        self.supabase_manager = supabase_manager
        self._recording_threads = {}
        self._lock = threading.Lock()

    def set_supabase_manager(self, supabase_manager):
        """Set or update the Supabase manager."""
        self.supabase_manager = supabase_manager

    def save_snapshot(self, camera_id: int, frame, event_type: str = "motion") -> Tuple[Optional[str], Optional[str]]:
        """
        Save a snapshot image from a detection event.
        Returns: (local_relative_path, supabase_public_url)
        """
        try:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            date_dir = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            save_dir = os.path.join(self.config.SNAPSHOTS_DIR, str(camera_id), date_dir)
            os.makedirs(save_dir, exist_ok=True)

            filename = f"{event_type}_{timestamp}.jpg"
            filepath = os.path.join(save_dir, filename)

            cv2.imwrite(filepath, frame, [cv2.IMWRITE_JPEG_QUALITY, self.config.SNAPSHOT_QUALITY])

            rel_path = os.path.relpath(filepath, self.config.SNAPSHOTS_DIR).replace("\\", "/")
            logger.info(f"Local snapshot saved: {rel_path}")

            # Upload to Supabase Storage if enabled
            public_url = None
            if self.supabase_manager and self.supabase_manager.enabled:
                remote_name = f"cam_{camera_id}/{date_dir}/{filename}"
                public_url = self.supabase_manager.upload_snapshot(filepath, remote_name)

            return rel_path, public_url

        except Exception as e:
            logger.error(f"Failed to save snapshot for camera {camera_id}: {e}")
            return None, None

    def record_clip(self, camera_id: int, duration: Optional[int] = None,
                    on_complete=None) -> Optional[str]:
        """
        Record a video clip from a camera.
        Returns the relative path to the local clip file.
        """
        if duration is None:
            duration = self.config.RECORDING_SEGMENT_DURATION

        # Prevent multiple simultaneous recordings for the same camera
        with self._lock:
            if camera_id in self._recording_threads:
                logger.debug(f"Camera {camera_id} is already recording")
                return None

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        date_dir = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        save_dir = os.path.join(self.config.RECORDINGS_DIR, str(camera_id), date_dir)
        os.makedirs(save_dir, exist_ok=True)

        filename = f"clip_{timestamp}.mp4"
        filepath = os.path.join(save_dir, filename)
        rel_path = os.path.relpath(filepath, self.config.RECORDINGS_DIR).replace("\\", "/")

        thread = threading.Thread(
            target=self._record_thread,
            args=(camera_id, filepath, rel_path, date_dir, filename, duration, on_complete),
            daemon=True
        )

        with self._lock:
            self._recording_threads[camera_id] = thread

        thread.start()
        logger.info(f"Recording started for camera {camera_id}: {rel_path}")
        return rel_path

    def _record_thread(self, camera_id, filepath, rel_path, date_dir, filename, duration, on_complete):
        """Background thread to record video frames and upload to Supabase when done."""
        try:
            stream = self.camera_manager.get_stream(camera_id)
            if not stream:
                logger.error(f"Camera {camera_id} not found for recording")
                return

            frame = stream.get_frame()
            if frame is None:
                logger.error(f"Camera {camera_id}: No frame available for recording")
                return

            h, w = frame.shape[:2]
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            fps = min(stream.fps or 15, 30)
            if fps < 1:
                fps = 15

            writer = cv2.VideoWriter(filepath, fourcc, fps, (w, h))

            if not writer.isOpened():
                logger.error(f"Camera {camera_id}: Failed to create video writer")
                return

            start_time = time.time()
            frame_interval = 1.0 / fps

            while time.time() - start_time < duration:
                frame = stream.get_frame()
                if frame is not None:
                    ts_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    cv2.putText(frame, ts_text, (10, h - 20),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
                    cv2.putText(frame, ts_text, (10, h - 20),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1)
                    writer.write(frame)

                time.sleep(frame_interval)

            writer.release()
            logger.info(f"Recording complete for camera {camera_id}: {filepath}")

            # Upload to Supabase Storage if configured
            cloud_url = None
            if self.supabase_manager and self.supabase_manager.enabled:
                remote_name = f"cam_{camera_id}/{date_dir}/{filename}"
                cloud_url = self.supabase_manager.upload_recording(filepath, remote_name)

            if on_complete and callable(on_complete):
                try:
                    on_complete(camera_id, rel_path, cloud_url)
                except Exception as e:
                    logger.error(f"Error in on_complete recording callback: {e}")

        except Exception as e:
            logger.error(f"Recording error for camera {camera_id}: {e}")
        finally:
            with self._lock:
                self._recording_threads.pop(camera_id, None)

    def cleanup_old_recordings(self):
        """Delete local recordings older than MAX_RECORDING_DAYS."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.config.MAX_RECORDING_DAYS)
        deleted_count = 0

        for base_dir in [self.config.RECORDINGS_DIR, self.config.SNAPSHOTS_DIR]:
            if not os.path.exists(base_dir):
                continue

            for root, dirs, files in os.walk(base_dir, topdown=False):
                for name in files:
                    filepath = os.path.join(root, name)
                    try:
                        file_time = datetime.fromtimestamp(
                            os.path.getmtime(filepath), tz=timezone.utc
                        )
                        if file_time < cutoff:
                            os.remove(filepath)
                            deleted_count += 1
                    except Exception as e:
                        logger.error(f"Cleanup error for {filepath}: {e}")

                try:
                    if not os.listdir(root) and root != base_dir:
                        os.rmdir(root)
                except Exception:
                    pass

        if deleted_count > 0:
            logger.info(f"Cleanup: Deleted {deleted_count} old files")
        return deleted_count

    def get_storage_stats(self):
        """Get storage usage statistics."""
        stats = {
            "recordings_size": 0,
            "recordings_count": 0,
            "snapshots_size": 0,
            "snapshots_count": 0,
            "supabase_enabled": bool(self.supabase_manager and self.supabase_manager.enabled),
        }

        for base_dir, prefix in [
            (self.config.RECORDINGS_DIR, "recordings"),
            (self.config.SNAPSHOTS_DIR, "snapshots"),
        ]:
            if not os.path.exists(base_dir):
                continue
            for root, _, files in os.walk(base_dir):
                for name in files:
                    filepath = os.path.join(root, name)
                    stats[f"{prefix}_size"] += os.path.getsize(filepath)
                    stats[f"{prefix}_count"] += 1

        stats["recordings_size_mb"] = round(stats["recordings_size"] / (1024 * 1024), 1)
        stats["snapshots_size_mb"] = round(stats["snapshots_size"] / (1024 * 1024), 1)
        stats["total_size_mb"] = stats["recordings_size_mb"] + stats["snapshots_size_mb"]

        return stats
