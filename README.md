# 🎥 IntelliCam-SmartCCTV — AI-Powered Cloud Surveillance & Alert System

A cloud-ready, AI-powered CCTV/NVR application with **YOLOv8 object detection**, **ByteTrack persistent object tracking**, **Supabase cloud storage & PostgreSQL**, and **instant Telegram & WhatsApp mobile alerts**.



---

## 🌟 Key Capabilities

- **☁️ Zero-Laptop 24/7 Operation** — Host the server in the cloud (Supabase + Render/Railway or Supabase Edge Functions) so your laptop never needs to stay awake.
- **📱 Instant Telegram & WhatsApp Alerts** — Receive rich motion alerts directly on your phone with snapshot photos attached.
- **🗄️ Supabase Cloud Storage & Database** — Store event logs in Supabase PostgreSQL and snapshots/video clips in Supabase CDN Storage buckets.
- **🎯 AI Object Tracking (ByteTrack / Kalman)** — Assigns persistent track IDs (`#1 person`, `#2 car`) across frames with motion trail visualization.
- **🤖 YOLOv8 Detection** — Detects persons, vehicles (cars, motorcycles, trucks, buses, bicycles), and animals (dogs, cats, birds).
- **📡 Direct Camera Push Webhook** — Any IP camera (Tapo, Reolink, Dahua, Hikvision, ESP32-CAM) or phone app can HTTP POST motion snapshots directly to the cloud.
- **⚡ 100% Serverless Edge Function** — Deploy the included Deno/TypeScript Supabase Edge Function to handle motion alerts without running any VM.
- **📹 Multi-Stream Viewing** — Grid view with 1×1, 2×2, 3×3 layouts and real-time AI bounding box overlays.

---

## 🏗️ Zero-Laptop 24/7 Cloud Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       ZERO-LAPTOP 24/7 ARCHITECTURE                         │
└─────────────────────────────────────────────────────────────────────────────┘

  [ IP Camera / Old Phone / Sensor ]
                  │
                  ▼ (Direct HTTP POST on Motion / RTSP)
  ┌──────────────────────────────────────────────────────────────┐
  │                   CLOUD BACKEND PLATFORM                     │
  │                                                              │
  │  Option A: CC TV Cloud Server (Render / Railway / Docker)    │
  │  Option B: Pure Serverless Supabase Edge Function            │
  └───────────────┬──────────────────────────────┬───────────────┘
                  │                              │
                  ▼                              ▼
  ┌──────────────────────────────┐ ┌─────────────────────────────┐
  │       SUPABASE CLOUD         │ │    MOBILE NOTIFICATIONS     │
  │                              │ │                             │
  │ • PostgreSQL Database        │ │ • 📲 Telegram Bot (Photo)   │
  │   - Cameras, Events, Tracks  │ │   (100% Free, <1s delivery) │
  │ • Storage Buckets (CDN)      │ │ • 💬 WhatsApp Message       │
  │   - cctv-snapshots           │ │   (Twilio or Meta API)      │
  │   - cctv-recordings          │ │ • 🌐 Webhooks (HA / N8N)    │
  └──────────────────────────────┘ └─────────────────────────────┘
```

---

## 🚀 Pre-Configured Supabase Project

Your Supabase project is already created and verified:

- **Project Name:** `IntelliCam-SmartCCTV`
- **Project Ref:** `kuoljbtuexxqfvhkjsdc` (Region: `aws-1-ap-southeast-2` Sydney)
- **Supabase URL:** `https://kuoljbtuexxqfvhkjsdc.supabase.co`
- **Database Tables:** `cameras` and `events` (Created & Verified)
- **Storage Buckets:** `cctv-snapshots` and `cctv-recordings` (Created & Public)

### Connection Template for `.env`:

```env
# 1. Database Connection (Session Pooler - Port 5432)
DATABASE_URL=postgresql+psycopg2://postgres.kuoljbtuexxqfvhkjsdc:[YOUR-PASSWORD]@aws-1-ap-southeast-2.pooler.supabase.com:5432/postgres

# 2. Supabase Storage & API Keys
SUPABASE_URL=https://kuoljbtuexxqfvhkjsdc.supabase.co
SUPABASE_KEY=your_supabase_service_role_key
SUPABASE_BUCKET_SNAPSHOTS=cctv-snapshots
SUPABASE_BUCKET_RECORDINGS=cctv-recordings
```
*(Your real `SUPABASE_KEY`, database password, and configuration are already populated in your local `.env` file).*

---

## 📱 Setting Up Telegram Notifications (Recommended & 100% Free)

Telegram sends rich photo snapshots to your phone in under 1 second without any cost.

> **Pre-configured in your `.env`**:
> - **Bot:** `@DN_ROSHAN`
> - **Chat ID:** `6736440445`
> - **Status:** Enabled and verified live!

If setting up a new bot:
1. **Create a Bot**:
   - Open Telegram and search for `@BotFather`.
   - Send `/newbot`, name your bot (e.g. `MyHomeCCTVBot`), and copy the **Bot Token** (e.g. `712345678:AAH...`).
2. **Get your Chat ID**:
   - Open Telegram and message `@userinfobot` or `@RawDataBot`.
   - It will reply with your numeric `Id` (e.g. `987654321`).
3. **Start the Bot**:
   - Open your new bot's chat in Telegram and tap **Start**.
4. **Set in `.env`**:
   ```env
   TELEGRAM_ENABLED=True
   TELEGRAM_BOT_TOKEN=your_bot_token_here
   TELEGRAM_CHAT_ID=your_chat_id_here
   ```

---

## 💬 Setting Up WhatsApp Notifications

### Option A: Twilio WhatsApp (Easiest)
1. Sign up for a free sandbox at [twilio.com/console](https://www.twilio.com/console).
2. Go to **Messaging** -> **Try SMS / WhatsApp Sandbox**.
3. Send the sandbox code from your phone to connect your WhatsApp.
4. Set in `.env`:
   ```env
   WHATSAPP_ENABLED=True
   WHATSAPP_PROVIDER=twilio
   TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   TWILIO_AUTH_TOKEN=your_auth_token
   TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
   WHATSAPP_TO=whatsapp:+919876543210
   ```

---

## 📡 Direct Camera Push (Zero Laptop Needed)

If you don't want to run a local computer 24/7, you can configure your IP camera (or an app like *IP Webcam* on an old phone) to send an HTTP POST request whenever it detects motion:

**Webhook URL**:
```http
POST https://<your-cloud-domain>/api/camera-webhook?api_key=cctv-camera-secret-key
```

**Parameters (multipart form or JSON)**:
- `image`: Attach the JPEG snapshot file from the camera.
- `camera_name`: e.g. `Front Door`
- `type`: e.g. `motion` or `person`

When received, the cloud backend:
1. Uploads the snapshot to **Supabase Storage**.
2. Logs the detection event in **Supabase PostgreSQL**.
3. Immediately sends the snapshot photo to your **Telegram** and **WhatsApp**!

---

## ⚡ 100% Serverless Edge Function (Alternative)

If you want **zero servers** and only Supabase:
The `supabase/functions/motion-alert/index.ts` file can be deployed as a Supabase Edge Function:

```bash
# Install Supabase CLI
npm install -g supabase

# Link and deploy
supabase link --project-ref your-project-ref
supabase secrets set TELEGRAM_BOT_TOKEN=xxx TELEGRAM_CHAT_ID=yyy WEBHOOK_API_KEY=zzz
supabase functions deploy motion-alert --no-verify-jwt
```

Now, your cameras can POST directly to:
```
https://<project-ref>.supabase.co/functions/v1/motion-alert?api_key=zzz
```

---

## ☁️ Cloud Deployment (Render / Railway / Docker)

### Deploy to Render / Railway with 1 Click

1. Push your repository to GitHub.
2. In [Render](https://render.com) or [Railway](https://railway.app), create a new **Web Service** connected to your repo.
3. Select **Docker** or Python environment.
4. Set the Environment Variables from your `.env`:
   - `DATABASE_URL` (Supabase Postgres)
   - `SUPABASE_URL` & `SUPABASE_KEY`
   - `TELEGRAM_ENABLED=True`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
5. Click **Deploy**. Your CCTV dashboard and alert webhook are now running 24/7 in the cloud!

---

## 💻 Local Quick Start

```bash
# 1. Clone & enter directory
cd "IntelliCam-SmartCCTV"

# 2. Virtual environment
python -m venv venv
venv\Scripts\activate   # Windows
# source venv/bin/activate # Linux/Mac

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy and configure .env
cp .env.example .env

# 5. Start server
python app.py
```

Dashboard is live at **http://localhost:8080**.

---

## 📁 Project Structure

```
IntelliCam-SmartCCTV/
├── app.py                      # Flask REST API, WebSockets & Camera Webhook
├── config.py                   # Configuration (Supabase, Telegram, WhatsApp)
├── models.py                   # SQLAlchemy models (PostgreSQL / SQLite)
├── camera_manager.py           # Multi-camera streaming & AI overlay processor
├── detector.py                 # Motion + YOLOv8 + Object Tracking engine
├── tracker.py                  # MultiObjectTracker (ByteTrack / Kalman / Trails)
├── recorder.py                 # Snapshots & Video clip recording
├── notifier.py                 # Telegram, WhatsApp, WebSocket & Webhooks
├── supabase_manager.py         # Supabase Storage & CDN integration
├── supabase_schema.sql         # Supabase PostgreSQL & Storage setup SQL
├── supabase/
│   └── functions/
│       └── motion-alert/       # 100% Serverless Edge Function (Deno)
├── Dockerfile                  # Container definition for cloud deployment
├── docker-compose.yml          # Local containerized runner
├── requirements.txt            # Python dependencies
├── templates/                  # Web dashboard templates
│   ├── base.html
│   ├── dashboard.html
│   ├── events.html
│   ├── settings.html
│   └── player.html
└── static/                     # CSS & client-side JavaScript
```

---

## 📝 License

MIT License.
