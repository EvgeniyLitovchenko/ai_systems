// Спільний клієнт для chat.html і bench.html: один стрімінговий запит до мовної моделі з вимірюваннями.
//
// Два протоколи:
//   "openai" — OpenAI-сумісний API (/v1/chat/completions): Ollama, llama-server, LM Studio, vLLM;
//   "ollama" — рідний API Ollama (/api/chat): лише Ollama, але дозволяє задати розмір контексту й top_k.

/**
 * @param {object} cfg — налаштування: api, baseUrl, apiKey, model, maxTokens, temperature, topP, topK,
 *                       seed, reasoningEffort ("", "none", "low", "medium", "high"), numCtx
 * @param {Array} messages — історія діалогу [{role, content}]
 * @param {(text: string) => void} [onDelta] — викликається з кожним новим фрагментом відповіді
 * @param {AbortSignal} [signal]
 * @returns {Promise<{text, ttft, latency, tokens, tokensPerS, reasoning}>} — час у секундах
 */
export async function streamChat(cfg, messages, onDelta = () => {}, signal) {
  const start = performance.now();
  let first = null, text = "", tokens = null, reasoning = false;

  const onContent = (piece) => {
    if (!piece) return;
    if (first === null) first = performance.now();
    text += piece;
    onDelta(piece);
  };

  if (cfg.api === "ollama") {
    // Рідний API Ollama: відповідь приходить рядками JSON (NDJSON)
    const options = pick({ num_predict: cfg.maxTokens, temperature: cfg.temperature, top_p: cfg.topP,
                           top_k: cfg.topK, seed: cfg.seed, num_ctx: cfg.numCtx });
    const body = { model: cfg.model, messages, stream: true, options };
    if (cfg.reasoningEffort) body.think = cfg.reasoningEffort !== "none";
    const response = await post(`${ollamaRoot(cfg.baseUrl)}/api/chat`, body, cfg.apiKey, signal);
    for await (const line of readLines(response)) {
      if (!line.trim()) continue;
      const chunk = JSON.parse(line);
      if (chunk.error) throw new Error(chunk.error);
      if (chunk.message?.thinking) reasoning = true;
      onContent(chunk.message?.content);
      if (chunk.done) tokens = chunk.eval_count ?? null;
    }
  } else {
    // OpenAI-сумісний API: відповідь приходить як Server-Sent Events — рядки "data: {...}" і в кінці "data: [DONE]"
    const body = pick({ model: cfg.model, messages, stream: true, stream_options: { include_usage: true },
                        max_tokens: cfg.maxTokens, temperature: cfg.temperature, top_p: cfg.topP,
                        seed: cfg.seed, reasoning_effort: cfg.reasoningEffort || undefined });
    const response = await post(`${trimSlash(cfg.baseUrl)}/chat/completions`, body, cfg.apiKey, signal);
    for await (const line of readLines(response)) {
      if (!line.startsWith("data: ") || line === "data: [DONE]") continue;
      const chunk = JSON.parse(line.slice(6));
      if (chunk.usage) tokens = chunk.usage.completion_tokens;
      const delta = chunk.choices?.[0]?.delta;
      // Ollama надсилає міркування в полі reasoning, llama-server і vLLM — у reasoning_content
      if (delta?.reasoning || delta?.reasoning_content) reasoning = true;
      onContent(delta?.content);
    }
  }

  const end = performance.now();
  if (first === null) {
    throw new Error("модель не повернула жодного токена відповіді — якщо вона міркує, оберіть «без міркування»");
  }
  return {
    text,
    ttft: (first - start) / 1000,
    latency: (end - start) / 1000,
    tokens,
    tokensPerS: tokens > 1 && end > first ? (tokens - 1) / ((end - first) / 1000) : null,
    reasoning,
  };
}

/** Список моделей на сервері (працює для OpenAI-сумісного API й Ollama). */
export async function listModels(cfg) {
  const headers = cfg.apiKey ? { Authorization: `Bearer ${cfg.apiKey}` } : {};
  if (cfg.api === "ollama") {
    const data = await (await fetch(`${ollamaRoot(cfg.baseUrl)}/api/tags`, { headers })).json();
    return data.models.map((m) => m.name);
  }
  const data = await (await fetch(`${trimSlash(cfg.baseUrl)}/models`, { headers })).json();
  return data.data.map((m) => m.id);
}

/**
 * Параметри моделі за замовчуванням, якщо сервер — Ollama (через /api/show і /api/ps).
 * Повертає {temperature, top_p, top_k, loadedContext} або null для інших рантаймів.
 */
export async function modelDefaults(cfg) {
  try {
    const root = ollamaRoot(cfg.baseUrl);
    const show = await (await fetch(`${root}/api/show`, { method: "POST", body: JSON.stringify({ model: cfg.model }) })).json();
    const params = Object.fromEntries((show.parameters || "").split("\n")
      .map((line) => line.trim().split(/\s+/)).filter((parts) => parts.length === 2));
    const loaded = (await (await fetch(`${root}/api/ps`)).json()).models?.find((m) => m.name === cfg.model);
    return { temperature: params.temperature, top_p: params.top_p, top_k: params.top_k,
             loadedContext: loaded?.context_length };
  } catch {
    return null;  // не Ollama або сервер недоступний
  }
}

/** Перцентиль з лінійною інтерполяцією, як у bench.py і numpy.percentile. */
export function percentile(values, q) {
  const sorted = [...values].sort((a, b) => a - b);
  const position = (sorted.length - 1) * q / 100;
  const lower = Math.floor(position);
  const upper = Math.min(lower + 1, sorted.length - 1);
  return sorted[lower] + (sorted[upper] - sorted[lower]) * (position - lower);
}

/** Зберігає й відновлює значення полів форми між відкриттями сторінки (лише в цьому браузері). */
export function persistFields(storageKey, ids) {
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) || "{}");
    for (const id of ids) {
      const el = document.getElementById(id);
      if (id in saved) el.type === "checkbox" ? (el.checked = saved[id]) : (el.value = saved[id]);
      el.addEventListener("change", () => {
        saved[id] = el.type === "checkbox" ? el.checked : el.value;
        try { localStorage.setItem(storageKey, JSON.stringify(saved)); } catch {}
      });
    }
  } catch {}
}

/** Збирає налаштування з полів сторінки; порожні числові поля означають «значення сервера за замовчуванням». */
export function readSettings() {
  const num = (id) => {
    const value = document.getElementById(id).value.trim();
    return value === "" ? undefined : Number(value);
  };
  const api = document.getElementById("api").value;
  // порожнє текстове поле — значення з його сірої підказки (placeholder)
  const text = (id) => {
    const el = document.getElementById(id);
    return el.value.trim() || el.placeholder;
  };
  return {
    api,
    baseUrl: text("baseUrl"),
    apiKey: document.getElementById("apiKey").value.trim(),
    model: text("model"),
    maxTokens: num("maxTokens"),
    temperature: num("temperature"),
    topP: num("topP"),
    seed: num("seed"),
    reasoningEffort: document.getElementById("reasoningEffort").value,
    // top_k і розмір контексту має лише рідний API Ollama
    topK: api === "ollama" ? num("topK") : undefined,
    numCtx: api === "ollama" ? num("numCtx") : undefined,
  };
}

/** Вмикає поля, які має лише рідний API Ollama, тільки коли його обрано. */
export function syncOllamaOnlyFields() {
  const ollama = document.getElementById("api").value === "ollama";
  for (const el of document.querySelectorAll(".ollama-only input")) el.disabled = !ollama;
}

async function post(url, body, apiKey, signal) {
  const headers = { "Content-Type": "application/json" };
  if (apiKey) headers.Authorization = `Bearer ${apiKey}`;
  const response = await fetch(url, { method: "POST", headers, body: JSON.stringify(body), signal });
  if (!response.ok) throw new Error(`сервер відповів ${response.status}: ${(await response.text()).slice(0, 200)}`);
  return response;
}

async function* readLines(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop();  // неповний рядок лишаємо до наступного фрагмента
    yield* lines;
  }
  if (buffer) yield buffer;
}

function pick(object) {
  return Object.fromEntries(Object.entries(object).filter(([, v]) => v !== undefined && !Number.isNaN(v)));
}

function trimSlash(url) {
  return url.replace(/\/+$/, "");
}

function ollamaRoot(url) {
  return trimSlash(url).replace(/\/v1$/, "");
}
