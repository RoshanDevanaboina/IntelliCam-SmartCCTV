"""
CC TV — Configuration Management
Supports local SQLite or Supabase PostgreSQL, Supabase Storage,
Telegram & WhatsApp notifications, and cloud deployment.
"""
import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def get_database_url():
    """Retrieve and format database URI, converting postgres:// to postgresql:// if needed."""
    url = os.getenv("DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'cctv.db')}")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


class Config:
    """Application configuration."""

    # Flask
    SECRET_KEY = os.getenv("SECRET_KEY", "cctv-secret-key-change-in-production")
    DEBUG = os.getenv("DEBUG", "False").lower() == "true"

    # Database (Supabase PostgreSQL or local SQLite)
    SQLALCHEMY_DATABASE_URI = get_database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    } if "postgresql" in SQLALCHEMY_DATABASE_URI else {}

    # Supabase Cloud Integration
    SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")  # Anon or service role key
    SUPABASE_BUCKET_SNAPSHOTS = os.getenv("SUPABASE_BUCKET_SNAPSHOTS", "cctv-snapshots")
    SUPABASE_BUCKET_RECORDINGS = os.getenv("SUPABASE_BUCKET_RECORDINGS", "cctv-recordings")
    USE_SUPABASE_STORAGE = bool(SUPABASE_URL and SUPABASE_KEY)

    # Cloud Webhook API Key (for cameras pushing motion events directly)
    WEBHOOK_API_KEY = os.getenv("WEBHOOK_API_KEY", "cctv-camera-secret-key")

    # Telegram Notification Settings
    TELEGRAM_ENABLED = os.getenv("TELEGRAM_ENABLED", "False").lower() == "true"
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

    # WhatsApp Notification Settings
    WHATSAPP_ENABLED = os.getenv("WHATSAPP_ENABLED", "False").lower() == "true"
    WHATSAPP_PROVIDER = os.getenv("WHATSAPP_PROVIDER", "twilio").lower()  # "twilio" or "meta"
    # Twilio WhatsApp
    TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
    TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
    WHATSAPP_TO = os.getenv("WHATSAPP_TO", "")  # e.g. "whatsapp:+919876543210"
    # Meta Cloud API
    META_WHATSAPP_TOKEN = os.getenv("META_WHATSAPP_TOKEN", "")
    META_WHATSAPP_PHONE_ID = os.getenv("META_WHATSAPP_PHONE_ID", "")

    # Server
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", 8080))
    BASE_EXTERNAL_URL = os.getenv("BASE_EXTERNAL_URL", "")  # Public domain if hosted (e.g. https://my-cctv.onrender.com)

    # Local Storage paths (fallback and temporary caching)
    RECORDINGS_DIR = os.path.join(BASE_DIR, "recordings")
    SNAPSHOTS_DIR = os.path.join(BASE_DIR, "snapshots")

    # Recording settings
    RECORDING_SEGMENT_DURATION = int(os.getenv("RECORDING_SEGMENT_DURATION", 30))  # seconds
    MAX_RECORDING_DAYS = int(os.getenv("MAX_RECORDING_DAYS", 7))
    SNAPSHOT_QUALITY = int(os.getenv("SNAPSHOT_QUALITY", 85))  # JPEG quality

    # Detection settings
    MOTION_THRESHOLD = int(os.getenv("MOTION_THRESHOLD", 25))
    MOTION_MIN_AREA = int(os.getenv("MOTION_MIN_AREA", 500))
    OBJECT_CONFIDENCE = float(os.getenv("OBJECT_CONFIDENCE", 0.5))
    DETECTION_INTERVAL = float(os.getenv("DETECTION_INTERVAL", 0.5))  # seconds between detections

    # YOLO model
    YOLO_MODEL = os.getenv("YOLO_MODEL", "yolov8n.pt")  # nano model for speed

    # Tracking settings (ByteTrack / SORT)
    TRACKER_MAX_AGE = int(os.getenv("TRACKER_MAX_AGE", 30))  # frames to retain lost tracks
    TRACKER_MIN_HITS = int(os.getenv("TRACKER_MIN_HITS", 2))  # hits before confirming track
    TRACKER_IOU_THRESHOLD = float(os.getenv("TRACKER_IOU_THRESHOLD", 0.3))
    TRACKER_DRAW_TRAILS = os.getenv("TRACKER_DRAW_TRAILS", "True").lower() == "true"
    STREAM_OVERLAY = os.getenv("STREAM_OVERLAY", "True").lower() == "true"

    # Detection classes of interest (COCO dataset class IDs)
    DETECT_CLASSES = {
        0: "person",
        1: "bicycle",
        2: "car",
        3: "motorcycle",
        5: "bus",
        7: "truck",
        14: "bird",
        15: "cat",
        16: "dog",
    }

    # Stream settings
    STREAM_QUALITY = int(os.getenv("STREAM_QUALITY", 70))  # JPEG quality for MJPEG
    STREAM_FPS = int(os.getenv("STREAM_FPS", 15))
    RECONNECT_DELAY = int(os.getenv("RECONNECT_DELAY", 5))  # seconds

    @classmethod
    def init_dirs(cls):
        """Create required directories."""
        os.makedirs(cls.RECORDINGS_DIR, exist_ok=True)
        os.makedirs(cls.SNAPSHOTS_DIR, exist_ok=True)
