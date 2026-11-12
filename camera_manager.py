"""
CC TV — Camera Manager
Handles camera connections, frame capture, and MJPEG streaming.
"""
import cv2
import time
import threading
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


class CameraStream:
    """Manages a single camera stream."""

    def __init__(self, camera_id, source, source_type="rtsp"):
        self.camera_id = camera_id
        self.source = source
        self.source_type = source_type
        self.capture = None
        self.frame = None
        self.last_frame_time = 0
        self.running = False
        self.connected = False
        self.lock = threading.Lock()
        self.error = None
        self._thread = None
        self.fps = 0
        self._frame_count = 0
        self._fps_time = time.time()

    def _get_source(self):
        """Parse the camera source into an OpenCV-compatible source."""
        if self.source_type == "usb":
            try:
                return int(self.source)
            except ValueError:
                return 0
        return self.source

    def start(self):
        """Start the camera capture thread."""
        if self.running:
            return
        self.running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        logger.info(f"Camera {self.camera_id}: Started capture thread")

    def stop(self):
        """Stop the camera capture thread."""
        self.running = False
        if self._thread:
            self._thread.join(timeout=5)
        if self.capture:
            self.capture.release()
            self.capture = None
        self.connected = False
        logger.info(f"Camera {self.camera_id}: Stopped")

    def _connect(self):
        """Connect to the camera source."""
        try:
            source = self._get_source()
            self.capture = cv2.VideoCapture(source)

            if self.source_type == "rtsp":
                # Optimize for RTSP
                self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)

            if self.capture.isOpened():
                self.connected = True
                self.error = None
                logger.info(f"Camera {self.camera_id}: Connected to {self.source}")
                return True
            else:
                self.connected = False
                self.error = "Failed to open camera"
                logger.warning(f"Camera {self.camera_id}: {self.error}")
                return False
        except Exception as e:
            self.connected = False
            self.error = str(e)
            logger.error(f"Camera {self.camera_id}: Connection error — {e}")
            return False

    def _capture_loop(self):
        """Main capture loop running in a background thread."""
        reconnect_delay = 5

        while self.running:
            if not self.connected:
                if not self._connect():
                    time.sleep(reconnect_delay)
                    continue

            try:
                ret, frame = self.capture.read()
                if not ret:
                    logger.warning(f"Camera {self.camera_id}: Frame read failed, reconnecting...")
                    self.connected = False
                    if self.capture:
                        self.capture.release()
                    time.sleep(1)
                    continue

                with self.lock:
                    self.frame = frame
                    self.last_frame_time = time.time()

                # Calculate FPS
                self._frame_count += 1
                elapsed = time.time() - self._fps_time
                if elapsed >= 1.0:
                    self.fps = self._frame_count / elapsed
                    self._frame_count = 0
                    self._fps_time = time.time()

            except Exception as e:
                logger.error(f"Camera {self.camera_id}: Capture error — {e}")
                self.connected = False
                if self.capture:
                    self.capture.release()
                time.sleep(reconnect_delay)

    def get_frame(self):
        """Get the latest frame (thread-safe)."""
        with self.lock:
            if self.frame is not None:
                return self.frame.copy()
            return None

    def get_jpeg(self, quality=70):
        """Get the latest frame as JPEG bytes."""
        frame = self.get_frame()
        if frame is None:
            return None
        ret, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if ret:
            return jpeg.tobytes()
        return None

    def get_status(self):
        """Get the camera stream status."""
        return {
            "camera_id": self.camera_id,
            "connected": self.connected,
            "running": self.running,
            "fps": round(self.fps, 1),
            "error": self.error,
            "last_frame_time": self.last_frame_time,
        }


class CameraManager:
    """Manages all camera streams."""

    def __init__(self):
        self.streams = {}
        self.lock = threading.Lock()
        self._on_frame_callbacks = defaultdict(list)
        self.frame_processor = None

    def add_camera(self, camera_id, source, source_type="rtsp", auto_start=True):
        """Add and optionally start a camera stream."""
        with self.lock:
            if camera_id in self.streams:
                self.streams[camera_id].stop()

            stream = CameraStream(camera_id, source, source_type)
            self.streams[camera_id] = stream

            if auto_start:
                stream.start()

            logger.info(f"CameraManager: Added camera {camera_id}")
            return stream

    def remove_camera(self, camera_id):
        """Stop and remove a camera stream."""
        with self.lock:
            if camera_id in self.streams:
                self.streams[camera_id].stop()
                del self.streams[camera_id]
                logger.info(f"CameraManager: Removed camera {camera_id}")

    def get_stream(self, camera_id):
        """Get a camera stream by ID."""
        return self.streams.get(camera_id)

    def get_frame(self, camera_id):
        """Get the latest frame from a camera."""
        stream = self.streams.get(camera_id)
        if stream:
            return stream.get_frame()
        return None

    def get_jpeg(self, camera_id, quality=70, overlay=False):
        """Get the latest JPEG frame from a camera, optionally with AI overlay."""
        if overlay and self.frame_processor:
            try:
                frame = self.frame_processor(camera_id)
                if frame is not None:
                    ret, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
                    if ret:
                        return jpeg.tobytes()
            except Exception as e:
                logger.error(f"Error applying overlay to camera {camera_id}: {e}")

        stream = self.streams.get(camera_id)
        if stream:
            return stream.get_jpeg(quality)
        return None

    def generate_mjpeg(self, camera_id, quality=70, fps=15, overlay=False):
        """Generate MJPEG stream for a camera (generator for Flask response)."""
        frame_interval = 1.0 / fps

        while True:
            jpeg = self.get_jpeg(camera_id, quality=quality, overlay=overlay)
            if jpeg:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
                )
            else:
                # Send a placeholder frame (black image)
                placeholder = self._generate_placeholder()
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + placeholder + b"\r\n"
                )
            time.sleep(frame_interval)

    def _generate_placeholder(self):
        """Generate a placeholder 'no signal' image."""
        import numpy as np
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(img, "No Signal", (200, 240), cv2.FONT_HERSHEY_SIMPLEX,
                    1.5, (100, 100, 100), 3)
        _, jpeg = cv2.imencode(".jpg", img)
        return jpeg.tobytes()

    def get_all_status(self):
        """Get status of all camera streams."""
        statuses = {}
        for cam_id, stream in self.streams.items():
            statuses[cam_id] = stream.get_status()
        return statuses

    def stop_all(self):
        """Stop all camera streams."""
        for stream in self.streams.values():
            stream.stop()
        logger.info("CameraManager: Stopped all cameras")

    def restart_camera(self, camera_id):
        """Restart a camera stream."""
        stream = self.streams.get(camera_id)
        if stream:
            stream.stop()
            time.sleep(1)
            stream.start()
            return True
        return False
