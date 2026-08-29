import { ProxyError } from "./errors.ts";
import { isOperation, type Operation } from "./pricing.ts";

const FORBIDDEN_TOP = new Set([
  "user_id",
  "plan",
  "account_status",
  "ai_allowed",
  "budget",
  "used",
  "reserved",
  "actual_cost",
]);

const FORBIDDEN_PAYLOAD = new Set([
  "model",
  "endpoint",
  "raw_url",
  "headers",
  "api_key",
  "url",
  "authorization",
  "authorization_header",
]);

const MAX_VIEWS = 5;
const MAX_JPEG_CHARS = 12_000_000;
const MAX_QUERY = 2_000;
const MAX_DOCUMENT = 8_000;
const MAX_ITEMS = 40;
const MAX_USER_PROMPT = 16_000;

export type FactsPayload = {
  image_id: number;
  views: { label: string; image_jpeg_b64: string }[];
};

export type MeaningPayload = {
  query: string;
  items: { image_id: number; document: string }[];
};

export type ActPlanPayload = {
  user_prompt: string;
  previous_response_id: string;
};

export type ValidatedRequest =
  | { operation: "facts_generate"; payload: FactsPayload; requestId: string }
  | { operation: "meaning_search"; payload: MeaningPayload; requestId: string }
  | { operation: "act_plan"; payload: ActPlanPayload; requestId: string };

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function rejectForbidden(obj: Record<string, unknown>, names: Set<string>): void {
  for (const key of Object.keys(obj)) {
    if (names.has(key.toLowerCase())) {
      throw new ProxyError("invalid_payload");
    }
  }
}

function asInt(value: unknown): number | null {
  if (typeof value === "number" && Number.isInteger(value)) return value;
  if (typeof value === "string" && /^-?\d+$/.test(value)) return Number.parseInt(value, 10);
  return null;
}

export function validateRequest(body: unknown): ValidatedRequest {
  if (!isPlainObject(body)) throw new ProxyError("invalid_payload");
  rejectForbidden(body, FORBIDDEN_TOP);

  const operation = String(body.operation || "");
  if (!isOperation(operation) || operation === "other") {
    throw new ProxyError("invalid_operation");
  }
  if (!isPlainObject(body.payload)) throw new ProxyError("invalid_payload");
  rejectForbidden(body.payload, FORBIDDEN_PAYLOAD);

  const requestId = String(body.request_id || crypto.randomUUID()).slice(0, 80);

  if (operation === "facts_generate") {
    return { operation, payload: validateFacts(body.payload), requestId };
  }
  if (operation === "meaning_search") {
    return { operation, payload: validateMeaning(body.payload), requestId };
  }
  return { operation: "act_plan", payload: validateActPlan(body.payload), requestId };
}

function validateFacts(payload: Record<string, unknown>): FactsPayload {
  const imageId = asInt(payload.image_id);
  if (imageId === null) throw new ProxyError("invalid_payload");
  const views = payload.views;
  if (!Array.isArray(views) || views.length < 1 || views.length > MAX_VIEWS) {
    throw new ProxyError("invalid_payload");
  }
  const normalized = views.map((view) => {
    if (!isPlainObject(view)) throw new ProxyError("invalid_payload");
    rejectForbidden(view, FORBIDDEN_PAYLOAD);
    const label = String(view.label || "").trim().slice(0, 80);
    const raw = String(view.image_jpeg_b64 || "").replace(/^data:image\/[a-zA-Z0-9.+-]+;base64,/, "");
    if (!label || !raw || raw.length > MAX_JPEG_CHARS) throw new ProxyError("invalid_payload");
    if (!/^[A-Za-z0-9+/=\s]+$/.test(raw)) throw new ProxyError("invalid_payload");
    return { label, image_jpeg_b64: raw.replace(/\s+/g, "") };
  });
  return { image_id: imageId, views: normalized };
}

function validateMeaning(payload: Record<string, unknown>): MeaningPayload {
  const query = String(payload.query ?? "");
  if (!query || query.length > MAX_QUERY) throw new ProxyError("invalid_payload");
  const items = payload.items;
  if (!Array.isArray(items) || items.length < 1 || items.length > MAX_ITEMS) {
    throw new ProxyError("invalid_payload");
  }
  const normalized = items.map((item) => {
    if (!isPlainObject(item)) throw new ProxyError("invalid_payload");
    rejectForbidden(item, FORBIDDEN_PAYLOAD);
    const imageId = asInt(item.image_id);
    const document = String(item.document ?? "");
    if (imageId === null || !document || document.length > MAX_DOCUMENT) {
      throw new ProxyError("invalid_payload");
    }
    return { image_id: imageId, document };
  });
  return { query, items: normalized };
}

function validateActPlan(payload: Record<string, unknown>): ActPlanPayload {
  const userPrompt = String(payload.user_prompt ?? "");
  if (!userPrompt || userPrompt.length > MAX_USER_PROMPT) {
    throw new ProxyError("invalid_payload");
  }
  return {
    user_prompt: userPrompt,
    previous_response_id: normalizePreviousResponseId(payload.previous_response_id),
  };
}

function normalizePreviousResponseId(value: unknown): string {
  const text = String(value ?? "").trim();
  if (!text || text.length > 200) return "";
  if (!/^resp_[A-Za-z0-9_-]+$/.test(text)) return "";
  return text;
}

export function assertKnownOperation(operation: string): asserts operation is Operation {
  if (!isOperation(operation)) throw new ProxyError("invalid_operation");
}
