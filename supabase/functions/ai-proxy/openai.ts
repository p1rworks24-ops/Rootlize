import { ProxyError } from "./errors.ts";

const OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions";
const OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses";
const TIMEOUT_MS = 75_000;

export type OpenAIUsage = Record<string, unknown>;

export type OpenAIResult = {
  content: unknown;
  usage: OpenAIUsage;
  responseId?: string;
};

function classifyProviderStatus(status: number, stalePrevious = false): ProxyError {
  const options = { providerStatus: status, stalePrevious };
  if (status === 429) return new ProxyError("provider_rate_limited", "", options);
  if (status === 408 || status === 504) return new ProxyError("provider_timeout", "", options);
  if (status >= 500) return new ProxyError("provider_unavailable", "", options);
  return new ProxyError("provider_rejected", "", options);
}

export function isStalePreviousResponseError(error: unknown): boolean {
  if (!(error instanceof ProxyError)) return false;
  if (error.stalePrevious) return true;
  return error.providerStatus === 404;
}

export async function completeChat(body: Record<string, unknown>): Promise<OpenAIResult> {
  const payload = await postOpenAI(OPENAI_CHAT_URL, body);
  const content = payload?.choices?.[0]?.message?.content;
  if (content === undefined || content === null) {
    throw new ProxyError("provider_rejected");
  }
  return {
    content: parseJsonContent(content),
    usage: usageFrom(payload),
  };
}

export async function completeResponse(body: Record<string, unknown>): Promise<OpenAIResult> {
  const payload = await postOpenAI(OPENAI_RESPONSES_URL, body);
  const text = responseOutputText(payload);
  if (!text) throw new ProxyError("provider_rejected");
  return {
    content: parseJsonContent(text),
    usage: usageFrom(payload),
    responseId: String(payload?.id || ""),
  };
}

async function postOpenAI(url: string, body: Record<string, unknown>): Promise<Record<string, unknown>> {
  const apiKey = Deno.env.get("OPENAI_API_KEY") || "";
  if (!apiKey) throw new ProxyError("provider_unavailable");

  let lastError: ProxyError = new ProxyError("provider_unavailable");
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
    try {
      const response = await fetch(url, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${apiKey}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      if (!response.ok) {
        lastError = await classifyProviderFailure(response);
        if ((response.status === 429 || response.status >= 500) && attempt === 0) {
          continue;
        }
        throw lastError;
      }
      const payload = await response.json();
      if (!payload || typeof payload !== "object") {
        throw new ProxyError("provider_rejected");
      }
      return payload as Record<string, unknown>;
    } catch (error) {
      if (error instanceof ProxyError) {
        lastError = error;
        if (error.code === "provider_rate_limited" && attempt === 0) continue;
        throw error;
      }
      if (error instanceof DOMException && error.name === "AbortError") {
        lastError = new ProxyError("provider_timeout");
        if (attempt === 0) continue;
        throw lastError;
      }
      lastError = new ProxyError("provider_unavailable");
      if (attempt === 0) continue;
      throw lastError;
    } finally {
      clearTimeout(timer);
    }
  }
  throw lastError;
}

function parseJsonContent(content: unknown): unknown {
  if (typeof content !== "string") return content;
  try {
    return JSON.parse(content);
  } catch {
    throw new ProxyError("invalid_payload");
  }
}

async function classifyProviderFailure(response: Response): Promise<ProxyError> {
  let stalePrevious = false;
  try {
    const text = await response.text();
    stalePrevious = /previous[\s_-]*response/i.test(text);
  } catch {
    stalePrevious = false;
  }
  return classifyProviderStatus(response.status, stalePrevious);
}

function usageFrom(payload: Record<string, unknown>): OpenAIUsage {
  const usage = payload?.usage;
  return usage && typeof usage === "object" ? usage as OpenAIUsage : {};
}

function responseOutputText(payload: Record<string, unknown>): string {
  const direct = payload?.output_text;
  if (typeof direct === "string" && direct.trim()) return direct;
  const chunks: string[] = [];
  const output = payload?.output;
  if (!Array.isArray(output)) return "";
  for (const item of output) {
    if (!item || typeof item !== "object") continue;
    const content = (item as { content?: unknown }).content;
    if (!Array.isArray(content)) continue;
    for (const part of content) {
      if (!part || typeof part !== "object") continue;
      const text = (part as { text?: unknown }).text;
      if (typeof text === "string" && text) chunks.push(text);
    }
  }
  return chunks.join("");
}
