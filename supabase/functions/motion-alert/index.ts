/**
 * Supabase Edge Function: motion-alert
 * 
 * 100% Serverless 24/7 Motion Alert Receiver:
 * - Direct camera push target (no laptop or server required!)
 * - Stores snapshot in Supabase Storage ('cctv-snapshots')
 * - Inserts detection record into Supabase PostgreSQL ('events')
 * - Instantly dispatches Telegram Bot alert with photo or WhatsApp alert
 * 
 * Deploy via Supabase CLI:
 *   supabase functions deploy motion-alert --no-verify-jwt
 */

import { serve } from "https://deno.land/std@0.177.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.39.0";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type, x-api-key",
};

serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  try {
    const supabaseUrl = Deno.env.get("SUPABASE_URL") ?? "";
    const supabaseServiceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
    const telegramToken = Deno.env.get("TELEGRAM_BOT_TOKEN") ?? "";
    const telegramChatId = Deno.env.get("TELEGRAM_CHAT_ID") ?? "";
    const webhookApiKey = Deno.env.get("WEBHOOK_API_KEY") ?? "";

    // 1. Authentication check
    const apiKey = req.headers.get("x-api-key") || new URL(req.url).searchParams.get("api_key");
    if (webhookApiKey && apiKey && apiKey !== webhookApiKey) {
      return new Response(JSON.stringify({ error: "Unauthorized" }), {
        status: 401,
        headers: { ...corsHeaders, "Content-Type": "application/json" },
      });
    }

    const supabase = createClient(supabaseUrl, supabaseServiceKey);

    let cameraName = "Cloud Camera";
    let eventType = "motion";
    let imageBytes: Uint8Array | null = null;

    const contentType = req.headers.get("content-type") || "";

    // 2. Parse request (Multipart Form or JSON or Raw Image)
    if (contentType.includes("multipart/form-data")) {
      const formData = await req.formData();
      cameraName = (formData.get("camera_name") as string) || cameraName;
      eventType = (formData.get("type") as string) || eventType;

      const file = formData.get("image") || formData.get("file") || formData.get("photo");
      if (file instanceof File) {
        imageBytes = new Uint8Array(await file.arrayBuffer());
      }
    } else if (contentType.includes("application/json")) {
      const body = await req.json();
      cameraName = body.camera_name || cameraName;
      eventType = body.type || eventType;
      if (body.image_base64) {
        const binStr = atob(body.image_base64);
        imageBytes = new Uint8Array(binStr.length);
        for (let i = 0; i < binStr.length; i++) {
          imageBytes[i] = binStr.charCodeAt(i);
        }
      }
    } else if (contentType.startsWith("image/")) {
      imageBytes = new Uint8Array(await req.arrayBuffer());
    }

    // 3. Upload Snapshot to Supabase Storage
    let publicUrl: string | null = null;
    const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
    const dateDir = new Date().toISOString().split("T")[0];

    if (imageBytes && imageBytes.length > 0) {
      const filePath = `edge/${dateDir}/${eventType}_${timestamp}.jpg`;
      const { data: uploadData, error: uploadErr } = await supabase.storage
        .from("cctv-snapshots")
        .upload(filePath, imageBytes, {
          contentType: "image/jpeg",
          upsert: true,
        });

      if (!uploadErr && uploadData) {
        const { data: urlData } = supabase.storage
          .from("cctv-snapshots")
          .getPublicUrl(filePath);
        publicUrl = urlData?.publicUrl || null;
      }
    }

    // 4. Ensure camera exists in PostgreSQL
    let cameraId = 1;
    const { data: camData } = await supabase
      .from("cameras")
      .select("id")
      .eq("name", cameraName)
      .maybeSingle();

    if (camData) {
      cameraId = camData.id;
    } else {
      const { data: newCam } = await supabase
        .from("cameras")
        .insert({
          name: cameraName,
          source: "edge-function",
          source_type: "webhook",
          enabled: true,
        })
        .select()
        .single();
      if (newCam) cameraId = newCam.id;
    }

    // 5. Insert event into PostgreSQL
    const { data: eventData, error: eventErr } = await supabase
      .from("events")
      .insert({
        camera_id: cameraId,
        event_type: eventType,
        confidence: 1.0,
        snapshot_path: publicUrl,
        details: JSON.stringify({ source: "supabase_edge_function" }),
      })
      .select()
      .single();

    // 6. Send Telegram Alert with Photo
    if (telegramToken && telegramChatId) {
      const caption = `🚨 *CCTV ALERT: ${eventType.toUpperCase()}*\n📹 *Camera:* ${cameraName}\n🕒 *Time:* ${new Date().toLocaleString()}`;

      if (publicUrl) {
        await fetch(`https://api.telegram.org/bot${telegramToken}/sendPhoto`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            chat_id: telegramChatId,
            photo: publicUrl,
            caption: caption,
            parse_mode: "Markdown",
          }),
        });
      } else {
        await fetch(`https://api.telegram.org/bot${telegramToken}/sendMessage`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            chat_id: telegramChatId,
            text: caption,
            parse_mode: "Markdown",
          }),
        });
      }
    }

    return new Response(
      JSON.stringify({
        status: "success",
        event: eventData,
        snapshot_url: publicUrl,
        message: "Motion alert processed and notifications sent",
      }),
      {
        headers: { ...corsHeaders, "Content-Type": "application/json" },
        status: 200,
      }
    );
  } catch (err) {
    return new Response(JSON.stringify({ error: err.message }), {
      headers: { ...corsHeaders, "Content-Type": "application/json" },
      status: 500,
    });
  }
});
