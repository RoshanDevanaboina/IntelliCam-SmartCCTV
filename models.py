"""
CC TV — Database Models
"""
from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Camera(db.Model):
    """Camera configuration model."""
    __tablename__ = "cameras"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    source = db.Column(db.String(500), nullable=False)  # RTSP URL, device index, or file path
    source_type = db.Column(db.String(20), default="rtsp")  # rtsp, usb, file
    enabled = db.Column(db.Boolean, default=True)
    recording_enabled = db.Column(db.Boolean, default=True)
    motion_detection = db.Column(db.Boolean, default=True)
    object_detection = db.Column(db.Boolean, default=False)
    object_tracking = db.Column(db.Boolean, default=True)
    motion_sensitivity = db.Column(db.Integer, default=25)  # threshold value
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    events = db.relationship("Event", backref="camera", lazy="dynamic",
                             cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "source": self.source,
            "source_type": self.source_type,
            "enabled": self.enabled,
            "recording_enabled": self.recording_enabled,
            "motion_detection": self.motion_detection,
            "object_detection": self.object_detection,
            "object_tracking": self.object_tracking,
            "motion_sensitivity": self.motion_sensitivity,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Event(db.Model):
    """Detection event model."""
    __tablename__ = "events"

    id = db.Column(db.Integer, primary_key=True)
    camera_id = db.Column(db.Integer, db.ForeignKey("cameras.id"), nullable=False)
    event_type = db.Column(db.String(50), nullable=False)  # motion, person, car, etc.
    track_id = db.Column(db.Integer, nullable=True)  # tracked object persistent ID
    confidence = db.Column(db.Float, default=0.0)
    snapshot_path = db.Column(db.String(500), nullable=True)
    recording_path = db.Column(db.String(500), nullable=True)
    thumbnail_path = db.Column(db.String(500), nullable=True)
    details = db.Column(db.Text, nullable=True)  # JSON string with extra info
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "camera_id": self.camera_id,
            "camera_name": self.camera.name if self.camera else "Unknown",
            "event_type": self.event_type,
            "track_id": self.track_id,
            "confidence": self.confidence,
            "snapshot_path": self.snapshot_path,
            "recording_path": self.recording_path,
            "details": self.details,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
