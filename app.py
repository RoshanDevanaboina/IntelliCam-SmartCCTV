"""
CC TV — Main Application
AI-powered CCTV/NVR surveillance system.
"""
import os
import json
import logging
import time
from datetime import datetime, timezone
from flask import Flask, render_template, Response, request, jsonify, send_from_directory, redirect
from flask_socketio import SocketIO
from flask_cors import CORS
import cv2
import numpy as np

from config import Config
from models import db, Camera, Event
from camera_manager import CameraManager
from detector import DetectionEngine
from recorder import EventRecorder
from notifier import Notifier
from supabase_manager import SupabaseManager

# ─── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("cctv")

# ─── App Setup ───────────────────────────────────────────────────────────────

app = Flask(__name__)
app.config.from_object(Config)
CORS(app)

db.init_app(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# ─── Core Components ────────────────────────────────────────────────────────

Config.init_dirs()
supabase_manager = SupabaseManager(
    url=Config.SUPABASE_URL,
    key=Config.SUPABASE_KEY,
    snapshot_bucket=Config.SUPABASE_BUCKET_SNAPSHOTS,
    recording_bucket=Config.SUPABASE_BUCKET_RECORDINGS,
)
camera_manager = CameraManager()
recorder = EventRecorder(camera_manager, Config, supabase_manager=supabase_manager)
notifier = Notifier(socketio, config=Config)


def on_detection_event(camera_id, frame, event_info):
    """Callback when detection engine finds something."""
    with app.app_context():
        camera = db.session.get(Camera, camera_id)
        if not camera:
            return

        # Save snapshot (local disk & Supabase Storage)
        rel_snapshot_path, supabase_snapshot_url = recorder.save_snapshot(
            camera_id, frame, event_info["type"]
        )
        snapshot_to_store = supabase_snapshot_url or rel_snapshot_path

        # Start recording clip
        recording_path = None
        if camera.recording_enabled:
            def on_recording_done(cam_id, local_rel, cloud_url):
                with app.app_context():
                    ev = Event.query.filter_by(camera_id=cam_id).order_by(Event.id.desc()).first()
                    if ev:
                        ev.recording_path = cloud_url or local_rel
                        db.session.commit()

            recording_path = recorder.record_clip(camera_id, on_complete=on_recording_done)

        # Save event to database
        event = Event(
            camera_id=camera_id,
            event_type=event_info["type"],
            track_id=event_info.get("track_id"),
            confidence=event_info.get("confidence", 0),
            snapshot_path=snapshot_to_store,
            recording_path=recording_path,
            details=event_info.get("details"),
        )
        db.session.add(event)
        db.session.commit()

        # Send notification via WebSocket, Telegram, WhatsApp, Webhooks
        notifier.notify(
            event_type=event_info["type"],
            camera_id=camera_id,
            camera_name=camera.name,
            track_id=event_info.get("track_id"),
            confidence=event_info.get("confidence", 0),
            snapshot_path=rel_snapshot_path,
            snapshot_url=supabase_snapshot_url,
            details=event_info.get("details"),
        )


detection_engine = DetectionEngine(camera_manager, Config, event_callback=on_detection_event)
camera_manager.frame_processor = detection_engine.get_annotated_frame

# ─── Page Routes ─────────────────────────────────────────────────────────────


@app.route("/")
def dashboard():
    """Live view dashboard."""
    cameras = Camera.query.filter_by(enabled=True).all()
    return render_template("dashboard.html", cameras=cameras)


@app.route("/events")
def events_page():
    """Event timeline page."""
    return render_template("events.html")


@app.route("/settings")
def settings_page():
    """Settings page."""
    cameras = Camera.query.all()
    return render_template("settings.html", cameras=cameras)


@app.route("/player/<int:camera_id>")
def player_page(camera_id):
    """Single camera fullscreen player."""
    camera = db.session.get(Camera, camera_id)
    if not camera:
        return "Camera not found", 404
    return render_template("player.html", camera=camera)


# ─── Stream Routes ───────────────────────────────────────────────────────────


@app.route("/api/stream/<int:camera_id>")
def video_stream(camera_id):
    """MJPEG video stream for a camera."""
    quality = request.args.get("quality", Config.STREAM_QUALITY, type=int)
    fps = request.args.get("fps", Config.STREAM_FPS, type=int)
    overlay = request.args.get("overlay", str(getattr(Config, "STREAM_OVERLAY", True))).lower() in ("true", "1", "yes")
    return Response(
        camera_manager.generate_mjpeg(camera_id, quality=quality, fps=fps, overlay=overlay),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route("/api/snapshot/<int:camera_id>")
def snapshot(camera_id):
    """Get a JPEG snapshot from a camera."""
    overlay = request.args.get("overlay", "false").lower() in ("true", "1", "yes")
    jpeg = camera_manager.get_jpeg(camera_id, quality=Config.SNAPSHOT_QUALITY, overlay=overlay)
    if jpeg:
        return Response(jpeg, mimetype="image/jpeg")
    return "No frame available", 503


# ─── Camera API ──────────────────────────────────────────────────────────────


@app.route("/api/cameras", methods=["GET"])
def get_cameras():
    """List all cameras."""
    cameras = Camera.query.all()
    result = []
    for cam in cameras:
        cam_dict = cam.to_dict()
        status = camera_manager.get_stream(cam.id)
        cam_dict["status"] = status.get_status() if status else {"connected": False, "running": False}
        result.append(cam_dict)
    return jsonify(result)


@app.route("/api/cameras", methods=["POST"])
def add_camera():
    """Add a new camera."""
    data = request.get_json()
    if not data or not data.get("name") or not data.get("source"):
        return jsonify({"error": "Name and source are required"}), 400

    camera = Camera(
        name=data["name"],
        source=data["source"],
        source_type=data.get("source_type", "rtsp"),
        enabled=data.get("enabled", True),
        recording_enabled=data.get("recording_enabled", True),
        motion_detection=data.get("motion_detection", True),
        object_detection=data.get("object_detection", False),
        object_tracking=data.get("object_tracking", True),
        motion_sensitivity=data.get("motion_sensitivity", Config.MOTION_THRESHOLD),
    )
    db.session.add(camera)
    db.session.commit()

    # Start the camera stream
    if camera.enabled:
        camera_manager.add_camera(camera.id, camera.source, camera.source_type)
        detection_engine.update_camera(camera)

    logger.info(f"Camera added: {camera.name} ({camera.source})")
    return jsonify(camera.to_dict()), 201


@app.route("/api/cameras/<int:camera_id>", methods=["PUT"])
def update_camera(camera_id):
    """Update a camera's settings."""
    camera = db.session.get(Camera, camera_id)
    if not camera:
        return jsonify({"error": "Camera not found"}), 404

    data = request.get_json()
    was_enabled = camera.enabled

    for field in ["name", "source", "source_type", "enabled", "recording_enabled",
                  "motion_detection", "object_detection", "object_tracking", "motion_sensitivity"]:
        if field in data:
            setattr(camera, field, data[field])

    db.session.commit()

    # Handle enable/disable changes
    if camera.enabled and not was_enabled:
        camera_manager.add_camera(camera.id, camera.source, camera.source_type)
    elif not camera.enabled and was_enabled:
        camera_manager.remove_camera(camera.id)

    # Update detection settings
    detection_engine.update_camera(camera)

    logger.info(f"Camera updated: {camera.name}")
    return jsonify(camera.to_dict())


@app.route("/api/cameras/<int:camera_id>", methods=["DELETE"])
def delete_camera(camera_id):
    """Delete a camera."""
    camera = db.session.get(Camera, camera_id)
    if not camera:
        return jsonify({"error": "Camera not found"}), 404

    camera_manager.remove_camera(camera_id)
    db.session.delete(camera)
    db.session.commit()

    logger.info(f"Camera deleted: {camera.name}")
    return jsonify({"message": "Camera deleted"})


@app.route("/api/cameras/<int:camera_id>/restart", methods=["POST"])
def restart_camera(camera_id):
    """Restart a camera stream."""
    camera = db.session.get(Camera, camera_id)
    if not camera:
        return jsonify({"error": "Camera not found"}), 404

    camera_manager.remove_camera(camera_id)
    time.sleep(1)
    camera_manager.add_camera(camera.id, camera.source, camera.source_type)
    return jsonify({"message": "Camera restarted"})


# ─── Events API ──────────────────────────────────────────────────────────────


@app.route("/api/events", methods=["GET"])
def get_events():
    """List events with optional filtering."""
    camera_id = request.args.get("camera_id", type=int)
    event_type = request.args.get("type")
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)

    query = Event.query.order_by(Event.created_at.desc())

    if camera_id:
        query = query.filter_by(camera_id=camera_id)
    if event_type:
        query = query.filter_by(event_type=event_type)

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        "events": [e.to_dict() for e in pagination.items],
        "total": pagination.total,
        "pages": pagination.pages,
        "current_page": page,
    })


@app.route("/api/events/<int:event_id>", methods=["DELETE"])
def delete_event(event_id):
    """Delete an event."""
    event = db.session.get(Event, event_id)
    if not event:
        return jsonify({"error": "Event not found"}), 404

    # Delete associated files
    if event.snapshot_path:
        path = os.path.join(Config.SNAPSHOTS_DIR, event.snapshot_path)
        if os.path.exists(path):
            os.remove(path)
    if event.recording_path:
        path = os.path.join(Config.RECORDINGS_DIR, event.recording_path)
        if os.path.exists(path):
            os.remove(path)

    db.session.delete(event)
    db.session.commit()
    return jsonify({"message": "Event deleted"})


@app.route("/api/events/clear", methods=["POST"])
def clear_events():
    """Clear all events."""
    Event.query.delete()
    db.session.commit()
    return jsonify({"message": "All events cleared"})


# ─── Media Routes ────────────────────────────────────────────────────────────


@app.route("/media/snapshots/<path:filepath>")
def serve_snapshot(filepath):
    """Serve a snapshot image (local file or redirect to Supabase URL)."""
    if filepath.startswith("http://") or filepath.startswith("https://"):
        return redirect(filepath)
    return send_from_directory(Config.SNAPSHOTS_DIR, filepath)


@app.route("/media/recordings/<path:filepath>")
def serve_recording(filepath):
    """Serve a recording video (local file or redirect to Supabase URL)."""
    if filepath.startswith("http://") or filepath.startswith("https://"):
        return redirect(filepath)
    return send_from_directory(Config.RECORDINGS_DIR, filepath)


# ─── Cloud Camera Push Webhook (Zero-Laptop Mode) ────────────────────────────


@app.route("/api/camera-webhook", methods=["POST"])
def camera_webhook():
    """
    Direct Cloud Webhook for IP Cameras & Mobile Devices.
    Allows smart cameras (Tapo, Reolink, Dahua, Hikvision, ESP32-CAM, IP Webcam app)
    to push motion alerts directly to this cloud server.
    Saves to Supabase and immediately dispatches Telegram / WhatsApp alerts.
    No laptop required!
    """
    # 1. Authenticate with optional API key
    auth_key = request.headers.get("X-API-Key") or request.args.get("api_key")
    if Config.WEBHOOK_API_KEY and auth_key and auth_key != Config.WEBHOOK_API_KEY:
        return jsonify({"error": "Unauthorized: Invalid API key"}), 401

    camera_name = (
        request.form.get("camera_name")
        or request.args.get("camera_name")
        or "Cloud IP Camera"
    )
    event_type = (
        request.form.get("type")
        or request.args.get("type")
        or "motion"
    )
    try:
        confidence = float(request.form.get("confidence") or request.args.get("confidence", 1.0))
    except (ValueError, TypeError):
        confidence = 1.0

    # 2. Get or create camera entry in Supabase / DB
    camera = Camera.query.filter_by(name=camera_name).first()
    if not camera:
        camera = Camera(
            name=camera_name,
            source="cloud-push",
            source_type="webhook",
            enabled=True,
            recording_enabled=False,
            motion_detection=True,
            object_detection=False,
        )
        db.session.add(camera)
        db.session.commit()

    # 3. Read image attachment from multipart form or raw bytes
    frame = None
    image_file = (
        request.files.get("image")
        or request.files.get("file")
        or request.files.get("photo")
        or request.files.get("snapshot")
    )

    if image_file:
        file_bytes = np.frombuffer(image_file.read(), np.uint8)
        frame = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
    elif request.data and request.content_type in ("image/jpeg", "image/png"):
        file_bytes = np.frombuffer(request.data, np.uint8)
        frame = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)

    snapshot_path = None
    snapshot_url = None

    if frame is not None:
        rel_path, cloud_url = recorder.save_snapshot(camera.id, frame, event_type)
        snapshot_path = rel_path
        snapshot_url = cloud_url

    # 4. Save Event to DB
    event = Event(
        camera_id=camera.id,
        event_type=event_type,
        confidence=confidence,
        snapshot_path=snapshot_url or snapshot_path,
        details=json.dumps({"source": "cloud_camera_webhook"}),
    )
    db.session.add(event)
    db.session.commit()

    # 5. Dispatch Telegram, WhatsApp & Webhook alerts immediately
    notifier.notify(
        event_type=event_type,
        camera_id=camera.id,
        camera_name=camera.name,
        confidence=confidence,
        snapshot_path=snapshot_path,
        snapshot_url=snapshot_url,
        details="Triggered via Cloud Camera Webhook",
    )

    return jsonify({
        "status": "success",
        "event_id": event.id,
        "camera": camera.name,
        "snapshot_url": snapshot_url or snapshot_path,
        "message": "Alert logged and sent to Telegram/WhatsApp"
    }), 201


@app.route("/api/notifications/test", methods=["POST"])
def test_notification():
    """Trigger a test alert to verify Telegram and WhatsApp delivery."""
    data = request.get_json(silent=True) or {}
    channel = data.get("channel", "all")

    notifier.notify(
        event_type="test_alert",
        camera_id=0,
        camera_name="System Test",
        confidence=1.0,
        details=f"Test alert triggered from dashboard for channel: {channel}",
    )
    return jsonify({
        "message": f"Test alert dispatched! Check Telegram and WhatsApp."
    })


# ─── System API ──────────────────────────────────────────────────────────────


@app.route("/api/status")
def system_status():
    """Get system status including cloud and notification health."""
    cameras_status = camera_manager.get_all_status()
    storage = recorder.get_storage_stats()
    camera_count = Camera.query.count()
    event_count = Event.query.count()
    enabled_count = Camera.query.filter_by(enabled=True).count()

    return jsonify({
        "cameras": {
            "total": camera_count,
            "enabled": enabled_count,
            "streams": cameras_status,
        },
        "events": {
            "total": event_count,
        },
        "storage": storage,
        "cloud": {
            "supabase_enabled": bool(supabase_manager and supabase_manager.enabled),
            "supabase_url": Config.SUPABASE_URL if Config.SUPABASE_URL else "Not configured",
            "database": "Supabase PostgreSQL" if "postgresql" in Config.SQLALCHEMY_DATABASE_URI else "Local SQLite",
        },
        "notifications": {
            "telegram_enabled": bool(Config.TELEGRAM_ENABLED and Config.TELEGRAM_BOT_TOKEN),
            "whatsapp_enabled": bool(Config.WHATSAPP_ENABLED),
            "whatsapp_provider": Config.WHATSAPP_PROVIDER if Config.WHATSAPP_ENABLED else None,
            "recent": notifier.get_recent(5),
        },
    })


@app.route("/api/notifications/recent")
def recent_notifications():
    """Get recent notifications."""
    limit = request.args.get("limit", 20, type=int)
    return jsonify(notifier.get_recent(limit))


@app.route("/api/storage/cleanup", methods=["POST"])
def cleanup_storage():
    """Trigger storage cleanup."""
    deleted = recorder.cleanup_old_recordings()
    return jsonify({"message": f"Deleted {deleted} old files"})


# ─── WebSocket Events ───────────────────────────────────────────────────────


@socketio.on("connect")
def handle_connect():
    logger.info("Client connected via WebSocket")


@socketio.on("disconnect")
def handle_disconnect():
    logger.info("Client disconnected from WebSocket")


# ─── Initialization ─────────────────────────────────────────────────────────


def init_cameras():
    """Initialize camera streams from database on startup."""
    with app.app_context():
        cameras = Camera.query.filter_by(enabled=True).all()
        for cam in cameras:
            camera_manager.add_camera(cam.id, cam.source, cam.source_type)
        logger.info(f"Initialized {len(cameras)} camera(s)")

        # Start detection engine
        detection_engine.start(cameras)


# ─── Main ────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        logger.info("Database tables created")

    init_cameras()

    logger.info(f"CC TV starting on http://{Config.HOST}:{Config.PORT}")
    print(f"""
╔══════════════════════════════════════════════════╗
║                                                  ║
║               🎥  CC TV  🎥                      ║
║         AI-Powered Surveillance System           ║
║                                                  ║
║   Dashboard:  http://localhost:{Config.PORT}             ║
║                                                  ║
╚══════════════════════════════════════════════════╝
    """)

    try:
        socketio.run(
            app,
            host=Config.HOST,
            port=Config.PORT,
            debug=Config.DEBUG,
            use_reloader=False,
            allow_unsafe_werkzeug=True,
        )
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        detection_engine.stop()
        camera_manager.stop_all()
