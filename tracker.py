"""
CC TV — Object Tracker
Multi-object tracking using IoU matching + Kalman filtering (SORT/ByteTrack style).
Assigns persistent IDs to detected objects across frames.
"""
import numpy as np
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


class KalmanBoxTracker:
    """
    Kalman filter-based tracker for a single bounding box.
    State: [x_center, y_center, area, aspect_ratio, vx, vy, va]
    """
    _id_counter = 0

    def __init__(self, bbox, class_name="unknown", confidence=0.0):
        KalmanBoxTracker._id_counter += 1
        self.id = KalmanBoxTracker._id_counter
        self.class_name = class_name
        self.confidence = confidence
        self.hits = 1           # total detection matches
        self.age = 0            # frames since creation
        self.time_since_update = 0  # frames since last match
        self.history = []       # recent positions for trail

        # Convert bbox [x1,y1,x2,y2] to state [cx, cy, area, ratio]
        x1, y1, x2, y2 = bbox
        cx = (x1 + x2) / 2.0
        cy = (y1 + y2) / 2.0
        w = x2 - x1
        h = y2 - y1
        area = w * h
        ratio = w / max(h, 1e-6)

        # State vector: [cx, cy, area, ratio, vcx, vcy, va]
        self.state = np.array([cx, cy, area, ratio, 0.0, 0.0, 0.0], dtype=np.float64)

        # Simple covariance (diagonal)
        self.P = np.eye(7) * 10.0
        self.P[4:, 4:] *= 100.0  # high uncertainty on velocities

        # Process noise
        self.Q = np.eye(7) * 1.0
        self.Q[4:, 4:] *= 0.01

        # Measurement noise
        self.R = np.eye(4) * 1.0

    def predict(self):
        """Predict next state using constant velocity model."""
        # State transition: position += velocity
        F = np.eye(7)
        F[0, 4] = 1.0  # cx += vcx
        F[1, 5] = 1.0  # cy += vcy
        F[2, 6] = 1.0  # area += va

        self.state = F @ self.state
        self.P = F @ self.P @ F.T + self.Q

        # Ensure area stays positive
        self.state[2] = max(self.state[2], 1.0)

        self.age += 1
        self.time_since_update += 1

        return self.get_bbox()

    def update(self, bbox, class_name=None, confidence=0.0):
        """Update state with a matched detection."""
        x1, y1, x2, y2 = bbox
        cx = (x1 + x2) / 2.0
        cy = (y1 + y2) / 2.0
        w = x2 - x1
        h = y2 - y1
        area = w * h
        ratio = w / max(h, 1e-6)

        measurement = np.array([cx, cy, area, ratio])

        # Kalman gain (simplified)
        H = np.zeros((4, 7))
        H[0, 0] = H[1, 1] = H[2, 2] = H[3, 3] = 1.0

        S = H @ self.P @ H.T + self.R
        try:
            K = self.P @ H.T @ np.linalg.inv(S)
        except np.linalg.LinAlgError:
            K = np.zeros((7, 4))

        innovation = measurement - H @ self.state
        self.state = self.state + K @ innovation
        self.P = (np.eye(7) - K @ H) @ self.P

        self.state[2] = max(self.state[2], 1.0)

        self.time_since_update = 0
        self.hits += 1
        if class_name:
            self.class_name = class_name
        self.confidence = confidence

        # Save position history for trail drawing
        bbox_now = self.get_bbox()
        cx_now = (bbox_now[0] + bbox_now[2]) / 2
        cy_now = (bbox_now[1] + bbox_now[3]) / 2
        self.history.append((int(cx_now), int(cy_now)))
        if len(self.history) > 30:
            self.history = self.history[-30:]

    def get_bbox(self):
        """Convert state back to [x1, y1, x2, y2]."""
        cx, cy, area, ratio = self.state[:4]
        area = max(area, 1.0)
        ratio = max(ratio, 0.01)
        w = np.sqrt(area * ratio)
        h = area / max(w, 1e-6)
        x1 = cx - w / 2.0
        y1 = cy - h / 2.0
        x2 = cx + w / 2.0
        y2 = cy + h / 2.0
        return [int(x1), int(y1), int(x2), int(y2)]

    def get_state(self):
        """Get tracker state as a dictionary."""
        bbox = self.get_bbox()
        return {
            "track_id": self.id,
            "class_name": self.class_name,
            "confidence": round(self.confidence, 3),
            "bbox": bbox,
            "age": self.age,
            "hits": self.hits,
            "time_since_update": self.time_since_update,
        }


def iou(bbox_a, bbox_b):
    """Compute IoU between two bounding boxes [x1,y1,x2,y2]."""
    x1 = max(bbox_a[0], bbox_b[0])
    y1 = max(bbox_a[1], bbox_b[1])
    x2 = min(bbox_a[2], bbox_b[2])
    y2 = min(bbox_a[3], bbox_b[3])

    inter_area = max(0, x2 - x1) * max(0, y2 - y1)
    if inter_area == 0:
        return 0.0

    area_a = max(0, bbox_a[2] - bbox_a[0]) * max(0, bbox_a[3] - bbox_a[1])
    area_b = max(0, bbox_b[2] - bbox_b[0]) * max(0, bbox_b[3] - bbox_b[1])

    union_area = area_a + area_b - inter_area
    return inter_area / max(union_area, 1e-6)


def compute_iou_matrix(trackers, detections):
    """Compute IoU cost matrix between trackers and detections."""
    n = len(trackers)
    m = len(detections)
    if n == 0 or m == 0:
        return np.empty((n, m))

    matrix = np.zeros((n, m))
    for i, trk in enumerate(trackers):
        trk_bbox = trk.get_bbox()
        for j, det in enumerate(detections):
            matrix[i, j] = iou(trk_bbox, det["bbox"])
    return matrix


def linear_assignment(cost_matrix, threshold=0.3):
    """
    Greedy assignment using IoU matrix. Returns matched pairs and unmatched indices.
    Uses scipy's linear_sum_assignment if available, otherwise greedy.
    """
    n, m = cost_matrix.shape
    if n == 0 or m == 0:
        return [], list(range(n)), list(range(m))

    try:
        from scipy.optimize import linear_sum_assignment as scipy_lsa
        # scipy minimizes cost, so we negate IoU
        row_indices, col_indices = scipy_lsa(-cost_matrix)

        matches = []
        unmatched_trackers = list(range(n))
        unmatched_detections = list(range(m))

        for r, c in zip(row_indices, col_indices):
            if cost_matrix[r, c] >= threshold:
                matches.append((r, c))
                if r in unmatched_trackers:
                    unmatched_trackers.remove(r)
                if c in unmatched_detections:
                    unmatched_detections.remove(c)

        return matches, unmatched_trackers, unmatched_detections

    except ImportError:
        # Fallback: greedy assignment
        return _greedy_assignment(cost_matrix, threshold)


def _greedy_assignment(cost_matrix, threshold):
    """Greedy matching fallback when scipy is not available."""
    n, m = cost_matrix.shape
    matched_trackers = set()
    matched_detections = set()
    matches = []

    # Flatten and sort by IoU (descending)
    pairs = []
    for i in range(n):
        for j in range(m):
            if cost_matrix[i, j] >= threshold:
                pairs.append((cost_matrix[i, j], i, j))
    pairs.sort(reverse=True)

    for _, i, j in pairs:
        if i not in matched_trackers and j not in matched_detections:
            matches.append((i, j))
            matched_trackers.add(i)
            matched_detections.add(j)

    unmatched_trackers = [i for i in range(n) if i not in matched_trackers]
    unmatched_detections = [j for j in range(m) if j not in matched_detections]

    return matches, unmatched_trackers, unmatched_detections


class MultiObjectTracker:
    """
    Multi-object tracker using IoU-based assignment with Kalman filtering.
    Similar to SORT (Simple Online and Realtime Tracking) / ByteTrack.
    """

    def __init__(self, max_age=30, min_hits=3, iou_threshold=0.3):
        """
        Args:
            max_age: Maximum frames to keep a tracker without updates before deletion.
            min_hits: Minimum detection hits before a track is considered confirmed.
            iou_threshold: Minimum IoU for a valid match.
        """
        self.max_age = max_age
        self.min_hits = min_hits
        self.iou_threshold = iou_threshold
        self.trackers = []
        self.frame_count = 0

        # Statistics
        self.total_tracks = 0
        self.active_object_counts = defaultdict(int)

    def update(self, detections):
        """
        Update trackers with new detections.

        Args:
            detections: list of dicts with keys: class_name, confidence, bbox [x1,y1,x2,y2]

        Returns:
            list of active track states (confirmed tracks only)
        """
        self.frame_count += 1

        # Predict new locations for all existing trackers
        for trk in self.trackers:
            trk.predict()

        # Match detections to existing trackers
        if len(self.trackers) > 0 and len(detections) > 0:
            iou_matrix = compute_iou_matrix(self.trackers, detections)
            matches, unmatched_trks, unmatched_dets = linear_assignment(
                iou_matrix, self.iou_threshold
            )
        else:
            matches = []
            unmatched_trks = list(range(len(self.trackers)))
            unmatched_dets = list(range(len(detections)))

        # Update matched trackers
        for trk_idx, det_idx in matches:
            det = detections[det_idx]
            self.trackers[trk_idx].update(
                det["bbox"],
                class_name=det.get("class_name"),
                confidence=det.get("confidence", 0),
            )

        # Create new trackers for unmatched detections
        for det_idx in unmatched_dets:
            det = detections[det_idx]
            trk = KalmanBoxTracker(
                det["bbox"],
                class_name=det.get("class_name", "unknown"),
                confidence=det.get("confidence", 0),
            )
            self.trackers.append(trk)
            self.total_tracks += 1

        # Remove dead trackers
        self.trackers = [
            trk for trk in self.trackers
            if trk.time_since_update <= self.max_age
        ]

        # Return confirmed tracks (enough hits and recently updated)
        active_tracks = []
        self.active_object_counts.clear()
        for trk in self.trackers:
            if trk.hits >= self.min_hits and trk.time_since_update <= 1:
                state = trk.get_state()
                state["trail"] = list(trk.history)
                active_tracks.append(state)
                self.active_object_counts[trk.class_name] += 1

        return active_tracks

    def get_statistics(self):
        """Get tracking statistics."""
        return {
            "total_tracks_created": self.total_tracks,
            "active_trackers": len(self.trackers),
            "confirmed_tracks": sum(
                1 for t in self.trackers
                if t.hits >= self.min_hits and t.time_since_update <= 1
            ),
            "object_counts": dict(self.active_object_counts),
            "frame_count": self.frame_count,
        }

    def reset(self):
        """Reset all trackers."""
        self.trackers.clear()
        self.total_tracks = 0
        self.active_object_counts.clear()
        self.frame_count = 0
        KalmanBoxTracker._id_counter = 0


def draw_tracks(frame, tracks, draw_trails=True):
    """
    Draw tracked objects with IDs and optional motion trails on a frame.

    Args:
        frame: OpenCV image (BGR)
        tracks: list of track states from MultiObjectTracker.update()
        draw_trails: whether to draw motion trails

    Returns:
        annotated frame
    """
    import cv2

    annotated = frame.copy()

    # Color palette for track IDs (consistent per ID)
    palette = [
        (255, 50, 50),    # Red
        (50, 255, 50),    # Green
        (50, 50, 255),    # Blue
        (255, 255, 50),   # Cyan
        (255, 50, 255),   # Magenta
        (50, 255, 255),   # Yellow
        (255, 128, 0),    # Orange
        (128, 0, 255),    # Purple
        (0, 255, 128),    # Spring green
        (255, 0, 128),    # Pink
    ]

    for track in tracks:
        track_id = track["track_id"]
        color = palette[track_id % len(palette)]
        x1, y1, x2, y2 = track["bbox"]
        label = f"#{track_id} {track['class_name']} {track['confidence']:.0%}"

        # Draw bounding box
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)

        # Draw label background
        (label_w, label_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(annotated, (x1, y1 - label_h - 10), (x1 + label_w + 4, y1), color, -1)
        cv2.putText(annotated, label, (x1 + 2, y1 - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)

        # Draw ID badge at center
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        id_text = f"#{track_id}"
        (id_w, id_h), _ = cv2.getTextSize(id_text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        cv2.circle(annotated, (cx, cy), max(id_w, id_h) // 2 + 8, color, -1)
        cv2.putText(annotated, id_text, (cx - id_w // 2, cy + id_h // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA)

        # Draw motion trail
        if draw_trails and "trail" in track and len(track["trail"]) > 1:
            trail = track["trail"]
            for i in range(1, len(trail)):
                # Fade trail: older points are more transparent
                alpha = i / len(trail)
                thickness = max(1, int(3 * alpha))
                trail_color = tuple(int(c * alpha) for c in color)
                cv2.line(annotated, trail[i - 1], trail[i], trail_color, thickness, cv2.LINE_AA)

    # Draw object count summary in top-right
    if tracks:
        counts = defaultdict(int)
        for t in tracks:
            counts[t["class_name"]] += 1

        y_offset = 30
        for cls_name, count in sorted(counts.items()):
            summary = f"{cls_name}: {count}"
            (sw, sh), _ = cv2.getTextSize(summary, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
            frame_w = annotated.shape[1]
            cv2.rectangle(annotated,
                          (frame_w - sw - 20, y_offset - sh - 5),
                          (frame_w - 5, y_offset + 5),
                          (0, 0, 0), -1)
            cv2.putText(annotated, summary,
                        (frame_w - sw - 15, y_offset),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA)
            y_offset += sh + 15

    return annotated
