import { createClient } from "npm:@supabase/supabase-js@2.57.4";

const ALLOWED_ORIGINS = new Set([
  "https://flowiq-crew-operations.vercel.app",
  "https://jay1125jay.github.io",
]);

const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
const ANON_KEY = Deno.env.get("SUPABASE_ANON_KEY") ?? "";
const admin = createClient(SUPABASE_URL, SERVICE_ROLE_KEY, {
  auth: { persistSession: false, autoRefreshToken: false },
});

type PushPayload = {
  worker_id: string;
  application_id?: string;
  job_id?: string;
  event_type: string;
};

function corsHeaders(req: Request) {
  const origin = req.headers.get("origin") ?? "";
  return {
    "Access-Control-Allow-Origin": ALLOWED_ORIGINS.has(origin) ? origin : "null",
    "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Vary": "Origin",
  };
}

function json(req: Request, body: Record<string, unknown>, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...corsHeaders(req), "Content-Type": "application/json; charset=utf-8" },
  });
}

function digits(value: unknown) {
  return String(value ?? "").replace(/\D/g, "");
}

async function sha256(value: string) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function enforceRateLimit(userId: string) {
  const actorHash = await sha256(`push|${userId}`);
  const since = new Date(Date.now() - 5 * 60 * 1000).toISOString();
  const { count, error } = await admin
    .from("wexa_auth_rate_limits")
    .select("id", { count: "exact", head: true })
    .eq("scope", "push")
    .eq("actor_hash", actorHash)
    .gte("created_at", since);
  if (error) throw new Error("RATE_LIMIT_CHECK_FAILED");
  if ((count ?? 0) >= 30) throw new Error("RATE_LIMITED");
  const { error: writeError } = await admin
    .from("wexa_auth_rate_limits")
    .insert({ scope: "push", actor_hash: actorHash });
  if (writeError) throw new Error("RATE_LIMIT_WRITE_FAILED");
}

async function authenticatedUser(req: Request) {
  const authHeader = req.headers.get("authorization") ?? "";
  const token = authHeader.startsWith("Bearer ") ? authHeader.slice(7) : "";
  if (!token || token === ANON_KEY) throw new Error("AUTH_REQUIRED");
  const authClient = createClient(SUPABASE_URL, ANON_KEY, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
  const { data, error } = await authClient.auth.getUser(token);
  if (error || !data.user) throw new Error("AUTH_REQUIRED");
  return data.user;
}

async function loadContext(payload: PushPayload) {
  const jobId = Number(payload.job_id || 0);
  const applicationId = Number(payload.application_id || 0);
  let job: Record<string, unknown> | null = null;
  let application: Record<string, unknown> | null = null;

  if (applicationId > 0) {
    const { data, error } = await admin
      .from("applications")
      .select("id,job_id,worker_user_id,company_user_id,worker_name,phone,status")
      .eq("id", applicationId)
      .maybeSingle();
    if (error || !data) throw new Error("APPLICATION_NOT_FOUND");
    application = data;
  }

  const resolvedJobId = jobId || Number(application?.job_id || 0);
  if (resolvedJobId > 0) {
    const { data, error } = await admin
      .from("jobs")
      .select("id,owner_user_id,company_id,company_name,title,work_date,work_start_date")
      .eq("id", resolvedJobId)
      .maybeSingle();
    if (error || !data) throw new Error("JOB_NOT_FOUND");
    job = data;
  }

  return { job, application };
}

function authorizeAndBuild(
  user: { id: string; app_metadata?: Record<string, unknown> },
  payload: PushPayload,
  context: { job: Record<string, unknown> | null; application: Record<string, unknown> | null },
) {
  const role = String(user.app_metadata?.role ?? "");
  const event = payload.event_type;
  const target = String(payload.worker_id ?? "");
  const job = context.job;
  const application = context.application;
  const jobTitle = String(job?.title ?? "근무 공고").slice(0, 80);
  const date = String(job?.work_date ?? job?.work_start_date ?? "").slice(0, 20);
  const tail = date ? ` · ${date}` : "";
  const workerName = String(application?.worker_name ?? "근로자").slice(0, 40);
  const companyName = String(job?.company_name ?? "업체").slice(0, 60);

  if (role === "admin" && event === "master_self_test" && target === "MASTER") {
    return {
      title: "WEXA 마스터 알림",
      body: "마스터 테스트 푸시가 정상 수신되었습니다.",
      link: "https://jay1125jay.github.io/flowiq-crew-masta/master.html",
    };
  }

  if (role === "worker") {
    if (!application || application.worker_user_id !== user.id) throw new Error("PUSH_FORBIDDEN");
    if (!["manager_new_application", "manager_application_cancelled", "master_new_application", "master_application_cancelled"].includes(event)) {
      throw new Error("PUSH_FORBIDDEN");
    }
    if (event.startsWith("manager_") && digits(target) !== digits(job?.company_id)) throw new Error("PUSH_TARGET_DENIED");
    if (event.startsWith("master_") && target !== "MASTER") throw new Error("PUSH_TARGET_DENIED");
    const cancelled = event.includes("cancelled");
    return {
      title: event.startsWith("master_") ? "WEXA 마스터 알림" : "WEXA 관리자 알림",
      body: cancelled
        ? `근로자가 신청을 취소했습니다. ${jobTitle}${tail} · ${workerName}`
        : `새 근무 신청이 도착했습니다. ${jobTitle}${tail} · ${workerName}`,
      link: event.startsWith("master_")
        ? "https://jay1125jay.github.io/flowiq-crew-masta/master.html"
        : "https://flowiq-crew-operations.vercel.app/operations.html",
    };
  }

  if (["business", "personal"].includes(role)) {
    if (!job || job.owner_user_id !== user.id) throw new Error("PUSH_FORBIDDEN");
    if (event === "master_new_job") {
      if (target !== "MASTER") throw new Error("PUSH_TARGET_DENIED");
      return {
        title: "WEXA 마스터 알림",
        body: `새 공고가 등록되었습니다. ${jobTitle}${tail} · ${companyName}`,
        link: "https://jay1125jay.github.io/flowiq-crew-masta/master.html",
      };
    }
    if (!["application_approved", "application_rejected", "work_completed"].includes(event)
      || !application
      || application.company_user_id !== user.id
      || digits(target) !== digits(application.phone)) {
      throw new Error("PUSH_FORBIDDEN");
    }
    const body = event === "application_approved"
      ? `근무 신청이 승인되었습니다. ${jobTitle}${tail}`
      : event === "application_rejected"
      ? `근무 신청이 반려되었습니다. ${jobTitle}${tail}`
      : `근무완료 처리가 완료되었습니다. ${jobTitle}${tail}`;
    return {
      title: "WEXA 근무 알림",
      body,
      link: "https://jay1125jay.github.io/-flowiq-crew-phon/",
    };
  }

  throw new Error("PUSH_FORBIDDEN");
}

function base64UrlEncode(input: ArrayBuffer | Uint8Array | string) {
  const bytes = typeof input === "string"
    ? new TextEncoder().encode(input)
    : input instanceof Uint8Array ? input : new Uint8Array(input);
  let binary = "";
  bytes.forEach((b) => (binary += String.fromCharCode(b)));
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function pemToArrayBuffer(pem: string) {
  const cleanPem = pem.replace(/\\n/g, "\n")
    .replace("-----BEGIN PRIVATE KEY-----", "")
    .replace("-----END PRIVATE KEY-----", "")
    .replace(/\s/g, "");
  const binary = atob(cleanPem);
  return Uint8Array.from(binary, (char) => char.charCodeAt(0)).buffer;
}

async function getFirebaseAccessToken() {
  const clientEmail = Deno.env.get("FIREBASE_CLIENT_EMAIL");
  const privateKey = Deno.env.get("FIREBASE_PRIVATE_KEY");
  if (!clientEmail || !privateKey) throw new Error("FIREBASE_CONFIG_MISSING");
  const now = Math.floor(Date.now() / 1000);
  const header = { alg: "RS256", typ: "JWT" };
  const claim = {
    iss: clientEmail,
    scope: "https://www.googleapis.com/auth/firebase.messaging",
    aud: "https://oauth2.googleapis.com/token",
    iat: now,
    exp: now + 3600,
  };
  const unsigned = `${base64UrlEncode(JSON.stringify(header))}.${base64UrlEncode(JSON.stringify(claim))}`;
  const key = await crypto.subtle.importKey(
    "pkcs8",
    pemToArrayBuffer(privateKey),
    { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = await crypto.subtle.sign(
    "RSASSA-PKCS1-v1_5",
    key,
    new TextEncoder().encode(unsigned),
  );
  const assertion = `${unsigned}.${base64UrlEncode(signature)}`;
  const response = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer",
      assertion,
    }),
  });
  const result = await response.json();
  if (!response.ok || !result.access_token) throw new Error("FIREBASE_AUTH_FAILED");
  return String(result.access_token);
}

async function activeTokens(workerId: string) {
  const { data, error } = await admin
    .from("worker_push_tokens")
    .select("id,fcm_token")
    .eq("worker_id", workerId)
    .eq("is_active", true);
  if (error) throw new Error("TOKEN_LOOKUP_FAILED");
  return data ?? [];
}

async function writeLog(args: {
  callerUserId: string;
  payload: PushPayload;
  title: string;
  body: string;
  status: string;
  error?: string;
}) {
  await admin.from("push_notification_logs").insert({
    caller_user_id: args.callerUserId,
    worker_id: args.payload.worker_id,
    application_id: args.payload.application_id ?? "",
    job_id: args.payload.job_id ?? "",
    event_type: args.payload.event_type,
    title: args.title,
    body: args.body,
    send_status: args.status,
    error_message: args.error ?? "",
    sent_at: args.status === "sent" ? new Date().toISOString() : null,
  });
}

async function sendFcm(
  token: string,
  payload: PushPayload,
  message: { title: string; body: string; link: string },
  accessToken: string,
) {
  const projectId = Deno.env.get("FIREBASE_PROJECT_ID") || "wexa-push";
  const response = await fetch(`https://fcm.googleapis.com/v1/projects/${projectId}/messages:send`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      message: {
        token,
        notification: { title: message.title, body: message.body },
        data: {
          worker_id: payload.worker_id,
          application_id: payload.application_id ?? "",
          job_id: payload.job_id ?? "",
          event_type: payload.event_type,
        },
        webpush: {
          notification: {
            title: message.title,
            body: message.body,
            icon: "/wexa-icon-192.png",
            badge: "/wexa-icon-192.png",
          },
          fcm_options: { link: message.link },
        },
      },
    }),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(`FCM_${response.status}`);
  return result;
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: corsHeaders(req) });
  if (req.method !== "POST") return json(req, { ok: false, code: "POST_ONLY" }, 405);
  const origin = req.headers.get("origin");
  if (origin && !ALLOWED_ORIGINS.has(origin)) return json(req, { ok: false, code: "ORIGIN_DENIED" }, 403);

  try {
    const user = await authenticatedUser(req);
    await enforceRateLimit(user.id);
    const payload = await req.json() as PushPayload;
    if (!payload.worker_id || !payload.event_type) throw new Error("INVALID_PAYLOAD");

    const context = await loadContext(payload);
    const message = authorizeAndBuild(user, payload, context);
    const tokens = await activeTokens(payload.worker_id);
    if (!tokens.length) {
      await writeLog({ callerUserId: user.id, payload, title: message.title, body: message.body, status: "skipped", error: "NO_ACTIVE_TOKEN" });
      return json(req, { ok: false, code: "NO_ACTIVE_TOKEN", sent: 0 }, 404);
    }

    const accessToken = await getFirebaseAccessToken();
    let sent = 0;
    let failed = 0;
    for (const item of tokens) {
      try {
        await sendFcm(item.fcm_token, payload, message, accessToken);
        sent += 1;
        await writeLog({ callerUserId: user.id, payload, title: message.title, body: message.body, status: "sent" });
      } catch (error) {
        failed += 1;
        const code = error instanceof Error ? error.message : "FCM_FAILED";
        await writeLog({ callerUserId: user.id, payload, title: message.title, body: message.body, status: "failed", error: code });
      }
    }
    return json(req, { ok: sent > 0, code: sent > 0 ? "PUSH_SENT" : "PUSH_FAILED", sent, failed }, sent > 0 ? 200 : 502);
  } catch (error) {
    const code = error instanceof Error ? error.message : "REQUEST_FAILED";
    const status = code === "RATE_LIMITED" ? 429
      : code === "AUTH_REQUIRED" ? 401
      : ["PUSH_FORBIDDEN", "PUSH_TARGET_DENIED"].includes(code) ? 403
      : ["INVALID_PAYLOAD", "APPLICATION_NOT_FOUND", "JOB_NOT_FOUND"].includes(code) ? 400
      : 500;
    const safeCode = status >= 500 ? "SERVER_ERROR" : code;
    console.error("WEXA push request failed", { code });
    return json(req, { ok: false, code: safeCode }, status);
  }
});
