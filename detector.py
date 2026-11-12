"""
CC TV — Motion & Object Detection
Handles motion detection via frame differencing and object detection via YOLOv8.
"""
import cv2
import numpy as np
import time
import threading
import logging
import json
from datetime import datetime, timezone
from tracker import MultiObjectTracker, draw_tracks

logger = logging.getLogger(__name__)


class MotionDetector:
    """Detects motion using background subtraction and contour analysis."""

    def __init__(self, threshold=25, min_area=500):
        self.threshold = threshold
        self.min_area = min_area
        self.bg_subtractor = cv2.createBackgroundSubtractorMOG2(
            history=500, varThreshold=threshold, detectShadows=True
        )
        self._warmup_frames = 0
        self._warmup_needed = 30  # frames to build background model

    def detect(self, frame):
        """
        Detect motion in a frame.
        Returns: (motion_detected: bool, contours: list, mask: ndarray)
        """
        # Apply background subtraction
        fg_mask = self.bg_subtractor.apply(frame)

        # Remove shadows (shadows have value 127 in MOG2)
        _, fg_mask = cv2.threshold(fg_mask, 200, 255, cv2.THRESH_BINARY)

        # Noise removal
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel)
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, kernel)
        fg_mask = cv2.dilate(fg_mask, kernel, iterations=2)

        # Warmup phase — let the background model stabilize
        self._warmup_frames += 1
        if self._warmup_frames < self._warmup_needed:
            return False, [], fg_mask

        # Find contours
        contours, _ = cv2.findContours(fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # Filter by minimum area
        significant_contours = [c for c in contours if cv2.contourArea(c) >= self.min_area]

        motion_detected = len(significant_contours) > 0

        return motion_detected, significant_contours, fg_mask

    def draw_motion(self, frame, contours):
        """Draw motion regions on a frame."""
        annotated = frame.copy()
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            cv2.rectangle(annotated, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.putText(annotated, "Motion", (x, y - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
        return annotated

    def update_sensitivity(self, threshold):
        """Update motion detection sensitivity."""
        self.threshold = threshold
        self.bg_subtractor = cv2.createBackgroundSubtractorMOG2(
            history=500, varThreshold=threshold, detectShadows=True
        )
        self._warmup_frames = 0


class ObjectDetector:
    """Detects objects using YOLOv8."""

    def __init__(self, model_path="yolov8n.pt", confidence=0.5, classes=None):
        self.model_path = model_path
        self.confidence = confidence
        self.classes = classes  # dict of {class_id: class_name}
        self.model = None
        self._loaded = False
        self._loading = False
        self._lock = threading.Lock()

    def _load_model(self):
        """Lazy-load the YOLO model."""
        if self._loaded:
            return True

        with self._lock:
            if self._loaded:
                return True
            if self._loading:
                return False

            self._loading = True
            try:
                from ultralytics import YOLO
                logger.info(f"Loading YOLO model: {self.model_path}")
                self.model = YOLO(self.model_path)
                self._loaded = True
                logger.info("YOLO model loaded successfully")
                return True
            except Exception as e:
                logger.error(f"Failed to load YOLO model: {e}")
                self._loading = False
                return False

    def detect(self, frame):
        """
        Detect objects in a frame.
        Returns: list of detections [{class_id, class_name, confidence, bbox}]
        """
        if not self._load_model():
            return []

        try:
            # Run inference
            results = self.model(frame, verbose=False, conf=self.confidence)

            detections = []
            for result in results:
                boxes = result.boxes
                if boxes is None:
                    continue

                for box in boxes:
                    class_id = int(box.cls[0])
                    conf = float(box.conf[0])

                    # Filter by classes of interest
                    if self.classes and class_id not in self.classes:
                        continue

                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    class_name = self.classes.get(class_id, f"class_{class_id}") if self.classes else result.names.get(class_id, f"class_{class_id}")

                    detections.append({
                        "class_id": class_id,
                        "class_name": class_name,
                        "confidence": round(conf, 3),
                        "bbox": [x1, y1, x2, y2],
                    })

            return detections
        except Exception as e:
            logger.error(f"Object detection error: {e}")
            return []

    def draw_detections(self, frame, detections):
        """Draw detection bounding boxes on a frame."""
        annotated = frame.copy()
        colors = {
            "person": (0, 0, 255),    # Red
            "car": (255, 0, 0),       # Blue
            "truck": (255, 0, 0),
            "bus": (255, 0, 0),
            "motorcycle": (255, 128, 0),
            "bicycle": (255, 128, 0),
            "dog": (0, 255, 255),     # Yellow
            "cat": (0, 255, 255),
            "bird": (0, 255, 255),
        }
        default_color = (0, 255, 0)

        for det in detections:
            x1, y1, x2, y2 = det["bbox"]
            color = colors.get(det["class_name"], default_color)
            label = f"{det['class_name']} {det['confidence']:.0%}"

            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)

            # Label background
            (label_w, label_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.rectangle(annotated, (x1, y1 - label_h - 10), (x1 + label_w, y1), color, -1)
            cv2.putText(annotated, label, (x1, y1 - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        return annotated


class DetectionEngine:
    """
    Combined detection engine that runs motion + object detection
    and multi-object tracking (persistent IDs) on camera feeds and triggers events.
    """

    def __init__(self, camera_manager, config, event_callback=None):
        self.camera_manager = camera_manager
        self.config = config
        self.event_callback = event_callback
        self.motion_detectors = {}   # camera_id -> MotionDetector
        self.trackers = {}           # camera_id -> MultiObjectTracker
        self.latest_tracks = {}      # camera_id -> {"time": float, "tracks": list}
        self.latest_motion = {}      # camera_id -> {"time": float, "contours": list}
        self.object_detector = None
        self.running = False
        self._threads = {}
        self._cooldowns = {}         # camera_id -> last_event_time (prevent spam)
        self._cooldown_period = 5    # seconds between events per camera
        self._lock = threading.Lock()

    def start(self, cameras):
        """Start detection for given cameras."""
        self.running = True
        for cam in cameras:
            if cam.motion_detection or cam.object_detection:
                self._start_camera_detection(cam)

    def _start_camera_detection(self, camera):
        """Start detection thread for a single camera."""
        cam_id = camera.id

        # Create motion detector
        if camera.motion_detection:
            self.motion_detectors[cam_id] = MotionDetector(
                threshold=camera.motion_sensitivity,
                min_area=self.config.MOTION_MIN_AREA
            )

        # Initialize object detector (shared across cameras)
        if camera.object_detection and not self.object_detector:
            self.object_detector = ObjectDetector(
                model_path=self.config.YOLO_MODEL,
                confidence=self.config.OBJECT_CONFIDENCE,
                classes=self.config.DETECT_CLASSES
            )

        # Initialize multi-object tracker for this camera
        if getattr(camera, "object_tracking", True):
            self.trackers[cam_id] = MultiObjectTracker(
                max_age=getattr(self.config, "TRACKER_MAX_AGE", 30),
                min_hits=getattr(self.config, "TRACKER_MIN_HITS", 2),
                iou_threshold=getattr(self.config, "TRACKER_IOU_THRESHOLD", 0.3),
            )

        # Start detection thread
        thread = threading.Thread(
            target=self._detection_loop, args=(camera,), daemon=True
        )
        self._threads[cam_id] = thread
        thread.start()
        logger.info(f"Detection started for camera {cam_id}")

    def _detection_loop(self, camera):
        """Detection loop for a single camera."""
        cam_id = camera.id
        interval = self.config.DETECTION_INTERVAL

        while self.running:
            try:
                frame = self.camera_manager.get_frame(cam_id)
                if frame is None:
                    time.sleep(interval)
                    continue

                events = []
                active_tracks = []
                motion_detected = False
                contours = []

                # Motion detection
                if camera.motion_detection and cam_id in self.motion_detectors:
                    motion_detected, contours, _ = self.motion_detectors[cam_id].detect(frame)
                    if motion_detected:
                        with self._lock:
                            self.latest_motion[cam_id] = {
                                "time": time.time(),
                                "contours": contours
                            }
                        total_area = sum(cv2.contourArea(c) for c in contours)
                        events.append({
                            "type": "motion",
                            "track_id": None,
                            "confidence": min(total_area / 50000.0, 1.0),
                            "details": json.dumps({"contour_count": len(contours), "total_area": int(total_area)}),
                        })

                # Object detection (runs when motion occurs or periodically)
                if camera.object_detection and self.object_detector and (events or not camera.motion_detection):
                    detections = self.object_detector.detect(frame)

                    # Multi-object tracking
                    if getattr(camera, "object_tracking", True):
                        if cam_id not in self.trackers:
                            self.trackers[cam_id] = MultiObjectTracker(
                                max_age=getattr(self.config, "TRACKER_MAX_AGE", 30),
                                min_hits=getattr(self.config, "TRACKER_MIN_HITS", 2),
                                iou_threshold=getattr(self.config, "TRACKER_IOU_THRESHOLD", 0.3),
                            )

                        active_tracks = self.trackers[cam_id].update(detections)

                        with self._lock:
                            self.latest_tracks[cam_id] = {
                                "time": time.time(),
                                "tracks": active_tracks
                            }

                        for trk in active_tracks:
                            events.append({
                                "type": trk["class_name"],
                                "track_id": trk["track_id"],
                                "confidence": trk["confidence"],
                                "details": json.dumps({
                                    "track_id": trk["track_id"],
                                    "class_name": trk["class_name"],
                                    "confidence": trk["confidence"],
                                    "bbox": trk["bbox"],
                                    "hits": trk["hits"],
                                    "age": trk["age"],
                                }),
                            })
                    else:
                        # Raw detections without tracking
                        for det in detections:
                            events.append({
                                "type": det["class_name"],
                                "track_id": None,
                                "confidence": det["confidence"],
                                "details": json.dumps(det),
                            })

                # Fire events (with cooldown)
                if events and self.event_callback:
                    now = time.time()
                    last_event = self._cooldowns.get(cam_id, 0)
                    if now - last_event >= self._cooldown_period:
                        self._cooldowns[cam_id] = now
                        # Prefer tracked objects over generic motion
                        tracked_events = [e for e in events if e.get("track_id") is not None]
                        best_event = max(tracked_events or events, key=lambda e: e["confidence"])

                        # Create annotated snapshot
                        annotated_snapshot = frame.copy()
                        if active_tracks:
                            annotated_snapshot = draw_tracks(
                                annotated_snapshot,
                                active_tracks,
                                draw_trails=getattr(self.config, "TRACKER_DRAW_TRAILS", True)
                            )
                        elif contours and camera.motion_detection and cam_id in self.motion_detectors:
                            annotated_snapshot = self.motion_detectors[cam_id].draw_motion(annotated_snapshot, contours)

                        self.event_callback(cam_id, annotated_snapshot, best_event)

                time.sleep(interval)

            except Exception as e:
                logger.error(f"Detection error on camera {cam_id}: {e}")
                time.sleep(interval * 2)

    def get_annotated_frame(self, camera_id, frame=None):
        """
        Overlay current active tracks and/or motion contours onto a frame.
        Useful for live MJPEG streams and snapshots.
        """
        if frame is None:
            frame = self.camera_manager.get_frame(camera_id)
            if frame is None:
                return None

        annotated = frame.copy()
        now = time.time()

        # Check for active tracks (valid within last 2 seconds)
        with self._lock:
            track_info = self.latest_tracks.get(camera_id)
            motion_info = self.latest_motion.get(camera_id)

        has_tracks = False
        if track_info and (now - track_info["time"]) < 2.0:
            tracks = track_info.get("tracks", [])
            if tracks:
                annotated = draw_tracks(
                    annotated,
                    tracks,
                    draw_trails=getattr(self.config, "TRACKER_DRAW_TRAILS", True)
                )
                has_tracks = True

        # Draw motion bounding boxes if no tracks were drawn
        if not has_tracks and motion_info and (now - motion_info["time"]) < 1.5:
            contours = motion_info.get("contours", [])
            detector = self.motion_detectors.get(camera_id)
            if contours and detector:
                annotated = detector.draw_motion(annotated, contours)

        return annotated

    def get_tracker_stats(self, camera_id=None):
        """Get statistics from the tracker."""
        with self._lock:
            if camera_id is not None:
                trk = self.trackers.get(camera_id)
                return trk.get_statistics() if trk else None

            stats = {}
            for cid, trk in self.trackers.items():
                stats[cid] = trk.get_statistics()
            return stats

    def stop(self):
        """Stop all detection threads."""
        self.running = False
        for thread in self._threads.values():
            thread.join(timeout=5)
        self._threads.clear()
        logger.info("Detection engine stopped")

    def update_camera(self, camera):
        """Update detection settings for a camera."""
        cam_id = camera.id

        # Update sensitivity if motion detector exists
        if cam_id in self.motion_detectors:
            self.motion_detectors[cam_id].update_sensitivity(camera.motion_sensitivity)

        # Handle tracker setup
        if getattr(camera, "object_tracking", True):
            if cam_id not in self.trackers:
                self.trackers[cam_id] = MultiObjectTracker(
                    max_age=getattr(self.config, "TRACKER_MAX_AGE", 30),
                    min_hits=getattr(self.config, "TRACKER_MIN_HITS", 2),
                    iou_threshold=getattr(self.config, "TRACKER_IOU_THRESHOLD", 0.3),
                )
        else:
            self.trackers.pop(cam_id, None)

        # If detection was just enabled, start a new thread
        if (camera.motion_detection or camera.object_detection) and cam_id not in self._threads:
            self._start_camera_detection(camera)
