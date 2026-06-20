const DEFAULT_ENDPOINT_URL = "http://127.0.0.1:9860/entry/openclaw-before-dispatch";
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
  id: "memcore-zhiyi-native",
  name: "Memcore Zhiyi Native",
  description: "Routes OpenClaw native webchat turns through memcore-cloud Zhiyi before provider dispatch.",
  register(api) {
    const config = normalizeConfig(api.pluginConfig);
    api.on("before_dispatch", async (event, ctx) => {
      if (!config.enabled) return;
      const channel = String(event?.channel || ctx?.channelId || "").trim().toLowerCase();
      if (config.allowedChannels.length > 0 && !config.allowedChannels.includes(channel)) return;
      const message = pickMessage(event);
      if (!message) return;

      const payload = buildPayload(event, ctx, config);
      const result = await postJson(config.endpointUrl, payload, config.timeoutMs, config.authToken);
      if (!result.ok) {
        api.logger?.warn?.(`memcore-zhiyi-native: ${result.error}`);
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
  pickMessage,
};
