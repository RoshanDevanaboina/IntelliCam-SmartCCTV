-- ═══════════════════════════════════════════════════════════════════════════════
-- CC TV — Supabase PostgreSQL Database & Storage Schema
-- Run this in your Supabase Dashboard -> SQL Editor
-- ═══════════════════════════════════════════════════════════════════════════════

-- 1. Create Cameras Table
CREATE TABLE IF NOT EXISTS public.cameras (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    source VARCHAR(500) NOT NULL,
    source_type VARCHAR(20) DEFAULT 'rtsp',
    enabled BOOLEAN DEFAULT true,
    recording_enabled BOOLEAN DEFAULT true,
    motion_detection BOOLEAN DEFAULT true,
    object_detection BOOLEAN DEFAULT false,
    object_tracking BOOLEAN DEFAULT true,
    motion_sensitivity INTEGER DEFAULT 25,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Create Events Table
CREATE TABLE IF NOT EXISTS public.events (
    id BIGSERIAL PRIMARY KEY,
    camera_id BIGINT REFERENCES public.cameras(id) ON DELETE CASCADE,
    event_type VARCHAR(50) NOT NULL,
    track_id INTEGER,
    confidence REAL DEFAULT 0.0,
    snapshot_path VARCHAR(500),
    recording_path VARCHAR(500),
    thumbnail_path VARCHAR(500),
    details TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. Create Indexes for High Performance Querying
CREATE INDEX IF NOT EXISTS idx_events_camera_id ON public.events(camera_id);
CREATE INDEX IF NOT EXISTS idx_events_created_at ON public.events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_type ON public.events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_track_id ON public.events(track_id);

-- 4. Set up Supabase Storage Buckets
-- Note: Buckets can also be created via Supabase Dashboard -> Storage
INSERT INTO storage.buckets (id, name, public)
VALUES ('cctv-snapshots', 'cctv-snapshots', true)
ON CONFLICT (id) DO UPDATE SET public = true;

INSERT INTO storage.buckets (id, name, public)
VALUES ('cctv-recordings', 'cctv-recordings', true)
ON CONFLICT (id) DO UPDATE SET public = true;

-- 5. Storage Security Policies (Allow Public Read & Authorized Upload)
CREATE POLICY "Public Read Access for Snapshots"
ON storage.objects FOR SELECT
USING (bucket_id = 'cctv-snapshots');

CREATE POLICY "Public Read Access for Recordings"
ON storage.objects FOR SELECT
USING (bucket_id = 'cctv-recordings');

CREATE POLICY "Allow Uploads to Snapshots"
ON storage.objects FOR INSERT
WITH CHECK (bucket_id = 'cctv-snapshots');

CREATE POLICY "Allow Uploads to Recordings"
ON storage.objects FOR INSERT
WITH CHECK (bucket_id = 'cctv-recordings');
