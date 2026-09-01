import { createClient } from "npm:@supabase/supabase-js@2.57.4";

const ALLOWED_ORIGINS = new Set([
  "https://flowiq-crew-operations.vercel.app",
  "https://jay1125jay.github.io",
]);

const supabaseUrl = Deno.env.get("SUPABASE_URL") ?? "";
const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
const anonKey = Deno.env.get("SUPABASE_ANON_KEY") ?? "";
const admin = createClient(supabaseUrl, serviceRoleKey, {
  auth: { persistSession: false, autoRefreshToken: false },
});
const publicAuth = createClient(supabaseUrl, anonKey, {
  auth: { persistSession: false, autoRefreshToken: false },
});

type AccountType = "worker" | "business" | "personal" | "admin";

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

function normalizePhone(value: unknown) {
  const raw = String(value ?? "").trim();
  let digits = raw.replace(/\D/g, "");
  if (digits.startsWith("82") && digits.length >= 11) digits = `0${digits.slice(2)}`;
  if (!/^01\d{8,9}$/.test(digits)) throw new Error("INVALID_PHONE");
  return { digits, e164: `+82${digits.slice(1)}` };
}

function validatePassword(value: unknown) {
  const password = String(value ?? "");
  if (password.length < 8 || password.length > 128) throw new Error("INVALID_PASSWORD");
  return password;
}

async function sha256(value: string) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function internalAuthEmail(phoneDigits: string) {
  const key = (await sha256(`wexa-login|${phoneDigits}`)).slice(0, 40);
  return `wexa.${key}@auth.wexa.invalid`;
}

function timingSafeEqual(left: string, right: string) {
  const a = new TextEncoder().encode(left);
  const b = new TextEncoder().encode(right);
  const size = Math.max(a.length, b.length);
  let diff = a.length ^ b.length;
  for (let i = 0; i < size; i += 1) diff |= (a[i] ?? 0) ^ (b[i] ?? 0);
  return diff === 0;
}

async function rateLimit(req: Request, scope: string, phone: string, limit = 5) {
  const ip = req.headers.get("x-forwarded-for")?.split(",")[0]?.trim()
    || req.headers.get("cf-connecting-ip")
    || "unknown";
  const actorHash = await sha256(`${scope}|${ip}|${phone}`);
  const since = new Date(Date.now() - 15 * 60 * 1000).toISOString();
  const { count, error } = await admin
    .from("wexa_auth_rate_limits")
    .select("id", { count: "exact", head: true })
    .eq("scope", scope)
    .eq("actor_hash", actorHash)
    .gte("created_at", since);
  if (error) throw new Error("RATE_LIMIT_CHECK_FAILED");
  if ((count ?? 0) >= limit) throw new Error("RATE_LIMITED");
  const { error: insertError } = await admin
    .from("wexa_auth_rate_limits")
    .insert({ scope, actor_hash: actorHash });
  if (insertError) throw new Error("RATE_LIMIT_WRITE_FAILED");
}

async function findAccount(phone: { digits: string; e164: string }) {
  const { data, error } = await admin
    .from("accounts")
    .select("id,type,name,phone,password,business_no,resident,bank,account,holder,auth_user_id")
    .in("phone", [phone.digits, phone.e164])
    .limit(1)
    .maybeSingle();
  if (error) throw new Error("ACCOUNT_LOOKUP_FAILED");
  return data;
}

async function backfillOwnership(account: { id: string; phone: string }) {
  const digits = String(account.phone ?? "").replace(/\D/g, "");
  const candidates = [account.phone, digits, `+82${digits.slice(1)}`].filter(Boolean);

  const { error: jobsError } = await admin
    .from("jobs")
    .update({ owner_user_id: account.id })
    .in("company_id", candidates)
    .is("owner_user_id", null);
  if (jobsError) console.error("WEXA ownership jobs backfill failed");

  const { error: workerAppsError } = await admin
    .from("applications")
    .update({ worker_user_id: account.id })
    .in("phone", candidates)
    .is("worker_user_id", null);
  if (workerAppsError) console.error("WEXA ownership worker applications backfill failed");

  const { error: companyAppsError } = await admin
    .from("applications")
    .update({ company_user_id: account.id })
    .in("company_id", candidates)
    .is("company_user_id", null);
  if (companyAppsError) console.error("WEXA ownership company applications backfill failed");

  const { error: workerAttendanceError } = await admin
    .from("attendance")
    .update({ worker_user_id: account.id })
    .in("phone", candidates)
    .is("worker_user_id", null);
  if (workerAttendanceError) console.error("WEXA ownership worker attendance backfill failed");

  const { error: companyAttendanceError } = await admin
    .from("attendance")
    .update({ company_user_id: account.id })
    .in("company_id", candidates)
    .is("company_user_id", null);
  if (companyAttendanceError) console.error("WEXA ownership company attendance backfill failed");

  const { error: tokenError } = await admin
    .from("worker_push_tokens")
    .update({ owner_user_id: account.id })
    .or(`phone.in.(${candidates.join(",")}),worker_id.in.(${candidates.join(",")})`)
    .is("owner_user_id", null);
  if (tokenError) console.error("WEXA ownership push token backfill failed");
}

async function createSecureUser(args: {
  id?: string;
  phone: string;
  password: string;
  type: AccountType;
  name: string;
}) {
  const email = await internalAuthEmail(args.phone.replace(/\D/g, ""));
  const { data, error } = await admin.auth.admin.createUser({
    ...(args.id ? { id: args.id } : {}),
    email,
    email_confirm: true,
    phone: args.phone,
    password: args.password,
    phone_confirm: true,
    app_metadata: { role: args.type },
    user_metadata: { name: args.name },
  });
  if (error || !data.user) throw new Error("AUTH_CREATE_FAILED");
  return data.user;
}

async function login(req: Request, input: Record<string, unknown>) {
  const phone = normalizePhone(input.phone);
  const password = validatePassword(input.password);
  await rateLimit(req, "login", phone.digits, 8);

  const account = await findAccount(phone);
  if (!account?.auth_user_id) throw new Error("LOGIN_DENIED");

  const email = await internalAuthEmail(phone.digits);
  const { error: aliasError } = await admin.auth.admin.updateUserById(account.auth_user_id, {
    email,
    email_confirm: true,
  });
  if (aliasError) throw new Error("LOGIN_PREPARE_FAILED");

  const { data, error } = await publicAuth.auth.signInWithPassword({ email, password });
  if (error || !data.session || !data.user) throw new Error("LOGIN_DENIED");
  if (data.user.id !== account.auth_user_id) throw new Error("LOGIN_DENIED");

  return json(req, {
    ok: true,
    code: "LOGIN_COMPLETE",
    session: {
      access_token: data.session.access_token,
      refresh_token: data.session.refresh_token,
      expires_at: data.session.expires_at,
    },
  });
}

async function signup(req: Request, input: Record<string, unknown>) {
  const phone = normalizePhone(input.phone);
  const password = validatePassword(input.password);
  const type = String(input.type ?? "") as AccountType;
  const name = String(input.name ?? "").trim().slice(0, 80);
  const holder = String(input.holder ?? "").trim().slice(0, 80);
  const businessNo = String(input.business_no ?? "").trim().slice(0, 30);
  if (!name || !["worker", "business", "personal"].includes(type)) throw new Error("INVALID_SIGNUP");
  if (type === "business" && !businessNo) throw new Error("BUSINESS_NO_REQUIRED");

  await rateLimit(req, "signup", phone.digits, 4);
  if (await findAccount(phone)) throw new Error("ACCOUNT_EXISTS");

  const id = crypto.randomUUID();
  const user = await createSecureUser({ id, phone: phone.e164, password, type, name });
  const { error } = await admin.from("accounts").insert({
    id: user.id,
    auth_user_id: user.id,
    type,
    name,
    phone: phone.digits,
    password: null,
    business_no: businessNo,
    resident: "",
    bank: "",
    account: "",
    holder: holder || name,
  });
  if (error) {
    await admin.auth.admin.deleteUser(user.id).catch(() => undefined);
    throw new Error("ACCOUNT_CREATE_FAILED");
  }
  return json(req, { ok: true, code: "SIGNUP_COMPLETE" });
}

async function migrate(req: Request, input: Record<string, unknown>) {
  const phone = normalizePhone(input.phone);
  const oldPassword = String(input.old_password ?? "");
  const newPassword = validatePassword(input.new_password);
  await rateLimit(req, "migrate", phone.digits, 5);

  const account = await findAccount(phone);
  if (!account || account.auth_user_id || !account.password
    || !timingSafeEqual(String(account.password), oldPassword)) {
    throw new Error("MIGRATION_DENIED");
  }

  const type = account.type as AccountType;
  if (!["worker", "business", "personal"].includes(type)) throw new Error("MIGRATION_DENIED");

  const user = await createSecureUser({
    id: account.id,
    phone: phone.e164,
    password: newPassword,
    type,
    name: String(account.name ?? "WEXA 회원"),
  });

  const { error } = await admin
    .from("accounts")
    .update({ auth_user_id: user.id, password: null })
    .eq("id", account.id)
    .is("auth_user_id", null);
  if (error) {
    await admin.auth.admin.deleteUser(user.id).catch(() => undefined);
    throw new Error("MIGRATION_SAVE_FAILED");
  }

  await backfillOwnership({ id: account.id, phone: account.phone });
  return json(req, { ok: true, code: "MIGRATION_COMPLETE" });
}

async function bootstrapAdmin(req: Request, input: Record<string, unknown>) {
  const phone = normalizePhone(input.phone);
  const password = validatePassword(input.password);
  const name = String(input.name ?? "WEXA MASTER").trim().slice(0, 80) || "WEXA MASTER";
  const setupCode = String(input.setup_code ?? "").trim();
  await rateLimit(req, "bootstrap_admin", phone.digits, 5);

  const { data: setting, error: settingError } = await admin
    .from("wexa_system_settings")
    .select("value,used_at")
    .eq("key", "admin_bootstrap")
    .maybeSingle();
  if (settingError || !setting || setting.used_at) throw new Error("BOOTSTRAP_CLOSED");
  const expectedHash = String(setting.value?.sha256 ?? "");
  const actualHash = await sha256(setupCode);
  if (!expectedHash || !timingSafeEqual(expectedHash, actualHash)) throw new Error("BOOTSTRAP_DENIED");

  const existing = await findAccount(phone);
  let userId = existing?.auth_user_id ?? existing?.id ?? crypto.randomUUID();

  if (existing?.auth_user_id) {
    const { error } = await admin.auth.admin.updateUserById(existing.auth_user_id, {
      password,
      phone: phone.e164,
      phone_confirm: true,
      app_metadata: { role: "admin" },
      user_metadata: { name },
    });
    if (error) throw new Error("ADMIN_AUTH_UPDATE_FAILED");
  } else {
    const user = await createSecureUser({ id: userId, phone: phone.e164, password, type: "admin", name });
    userId = user.id;
  }

  const profilePayload = {
    id: existing?.id ?? userId,
    auth_user_id: userId,
    type: "admin",
    name,
    phone: existing?.phone ?? phone.digits,
    password: null,
    business_no: existing?.business_no ?? "",
    resident: existing?.resident ?? "",
    bank: existing?.bank ?? "",
    account: existing?.account ?? "",
    holder: existing?.holder ?? name,
  };
  const { error: profileError } = await admin.from("accounts").upsert(profilePayload, { onConflict: "id" });
  if (profileError) throw new Error("ADMIN_PROFILE_SAVE_FAILED");

  const { error: closeError } = await admin
    .from("wexa_system_settings")
    .update({ used_at: new Date().toISOString(), value: { completed: true } })
    .eq("key", "admin_bootstrap")
    .is("used_at", null);
  if (closeError) throw new Error("BOOTSTRAP_CLOSE_FAILED");

  await backfillOwnership({ id: profilePayload.id, phone: profilePayload.phone });
  return json(req, { ok: true, code: "ADMIN_BOOTSTRAP_COMPLETE" });
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: corsHeaders(req) });
  if (req.method !== "POST") return json(req, { ok: false, code: "POST_ONLY" }, 405);

  const origin = req.headers.get("origin");
  if (origin && !ALLOWED_ORIGINS.has(origin)) return json(req, { ok: false, code: "ORIGIN_DENIED" }, 403);
  const length = Number(req.headers.get("content-length") ?? 0);
  if (length > 10_000) return json(req, { ok: false, code: "PAYLOAD_TOO_LARGE" }, 413);

  try {
    const input = await req.json() as Record<string, unknown>;
    const action = String(input.action ?? "");
    if (action === "signup") return await signup(req, input);
    if (action === "migrate") return await migrate(req, input);
    if (action === "bootstrap_admin") return await bootstrapAdmin(req, input);
    if (action === "login") return await login(req, input);
    return json(req, { ok: false, code: "INVALID_ACTION" }, 400);
  } catch (error) {
    const code = error instanceof Error ? error.message : "REQUEST_FAILED";
    const status = code === "RATE_LIMITED" ? 429
      : ["ACCOUNT_EXISTS", "INVALID_PHONE", "INVALID_PASSWORD", "INVALID_SIGNUP", "BUSINESS_NO_REQUIRED"].includes(code) ? 400
      : code === "LOGIN_DENIED" ? 401
      : ["MIGRATION_DENIED", "BOOTSTRAP_DENIED", "BOOTSTRAP_CLOSED"].includes(code) ? 403
      : 500;
    const safeCode = status >= 500 ? "SERVER_ERROR" : code;
    console.error("WEXA auth request failed", { code });
    return json(req, { ok: false, code: safeCode }, status);
  }
});
