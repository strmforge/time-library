import { readFileSync } from "node:fs";

const DEFAULT_ENDPOINT_URL = "";
const DEFAULT_TIMEOUT_MS = 120000;
const DEFAULT_ALLOWED_CHANNELS = ["webchat"];
const DEFAULT_FORCE_ZHIYI_DIRECT = false;

function asObject(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function asBool(value, fallback) {
  if (typeof value === "boolean") return value;
  return fallback;
}

function asPositiveInt(value, fallback, min, max) {
  const parsed = Number.parseInt(String(value ?? ""), 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(min, Math.min(max, parsed));
}

function normalizeConfig(raw) {
  const cfg = asObject(raw);
  const allowedChannels = Array.isArray(cfg.allowedChannels)
    ? cfg.allowedChannels.map((item) => String(item || "").trim().toLowerCase()).filter(Boolean)
    : DEFAULT_ALLOWED_CHANNELS;
  return {
    enabled: asBool(cfg.enabled, false),
    endpointUrl: String(cfg.endpointUrl || DEFAULT_ENDPOINT_URL),
    authToken: String(cfg.authToken || cfg.dialogEntryToken || ""),
    timeoutMs: asPositiveInt(cfg.timeoutMs, DEFAULT_TIMEOUT_MS, 500, 300000),
    allowedChannels,
    enableModelCall: asBool(cfg.enableModelCall, false),
    forceZhiyiDirect: asBool(cfg.forceZhiyiDirect, DEFAULT_FORCE_ZHIYI_DIRECT),
  };
}

function discoveryFile() {
  const root = process.env.TIME_LIBRARY_ROOT || process.env.MEMCORE_ROOT;
  if (root) return `${root}/runtime/front_door_port`;
  if (process.platform === "win32") {
    return `${process.env.LOCALAPPDATA || process.env.USERPROFILE || ""}/time-library/runtime/front_door_port`;
  }
  if (process.platform === "darwin") {
    return `${process.env.HOME || ""}/Library/Application Support/time-library/runtime/front_door_port`;
  }
  return `${process.env.HOME || ""}/.local/share/time-library/runtime/front_door_port`;
}

function resolveEndpoint(configured) {
  const explicit = String(configured || "").trim();
  if (explicit && !/127\.0\.0\.1:(9830|9840|9851|9860)(?:\/|$)/.test(explicit)) return explicit;
  try {
    const port = readFileSync(discoveryFile(), "utf8").trim();
    if (!/^\d{1,5}$/.test(port)) return explicit;
    return `http://127.0.0.1:${port}/entry/openclaw-before-dispatch`;
  } catch (_) {
    return explicit;
  }
}

function pickMessage(event) {
  return String(event?.content || event?.message || event?.body || "").trim();
}

async function postJson(url, payload, timeoutMs, authToken) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const headers = { "Content-Type": "application/json" };
  if (authToken) {
    headers.Authorization = `Bearer ${authToken}`;
  }
  try {
    const response = await fetch(url, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    if (!response.ok) {
      return { ok: false, error: `http_${response.status}` };
    }
    const body = await response.json();
    return { ok: true, body };
  } finally {
    clearTimeout(timer);
  }
}

function isLoopbackEndpoint(endpoint) {
  try {
    const host = new URL(endpoint).hostname.toLowerCase();
    return host === "127.0.0.1" || host === "localhost" || host === "::1" || host === "[::1]";
  } catch (_) {
    return false;
  }
}

async function verifyFrontDoor(endpoint, timeoutMs) {
  if (!isLoopbackEndpoint(endpoint)) return true;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), Math.min(timeoutMs, 1500));
  try {
    const health = new URL(endpoint);
    health.pathname = "/health";
    health.search = "";
    const response = await fetch(health, { method: "GET", signal: controller.signal });
    if (!response.ok) return false;
    const body = await response.json();
    return body?.ok === true
      && body?.service === "time-library-front-door"
      && body?.user_visible_address_count === 1;
  } catch (_) {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

function buildPayload(event, ctx, config) {
  return {
    message: pickMessage(event),
    session_key: event?.sessionKey || ctx?.sessionKey || "",
    channel: event?.channel || ctx?.channelId || "",
    sender_id: event?.senderId || ctx?.senderId || "",
    conversation_id: ctx?.conversationId || "",
    source_system: "openclaw",
    source: "openclaw_before_dispatch",
    model_call: {
      enabled: config.enableModelCall,
      provider: "hermes_cli",
      confirm_live_model_call: config.enableModelCall,
    },
    force_zhiyi_direct: config.forceZhiyiDirect,
  };
}

export default {
  id: "time-library-native",
  name: "Time Library Native",
  description: "Routes OpenClaw native webchat turns through Time Library recall before provider dispatch.",
  register(api) {
    const config = normalizeConfig(api.pluginConfig);
    api.on("before_dispatch", async (event, ctx) => {
      if (!config.enabled) return;
      const channel = String(event?.channel || ctx?.channelId || "").trim().toLowerCase();
      if (config.allowedChannels.length > 0 && !config.allowedChannels.includes(channel)) return;
      const message = pickMessage(event);
      if (!message) return;

      const payload = buildPayload(event, ctx, config);
      const endpoint = resolveEndpoint(config.endpointUrl);
      if (!endpoint) return;
      if (!(await verifyFrontDoor(endpoint, config.timeoutMs))) return;
      const result = await postJson(endpoint, payload, config.timeoutMs, config.authToken);
      if (!result.ok) {
        api.logger?.warn?.(`time-library-native: ${result.error}`);
        return;
      }
      const body = asObject(result.body);
      if (body.handled === true && typeof body.text === "string" && body.text.trim()) {
        return { handled: true, text: body.text.trim() };
      }
      return { handled: false };
    }, { timeoutMs: config.timeoutMs });
  },
};

export const testing = {
  buildPayload,
  normalizeConfig,
  resolveEndpoint,
  pickMessage,
};
