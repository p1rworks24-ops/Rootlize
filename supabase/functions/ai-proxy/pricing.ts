export const OPERATIONS = ["facts_generate", "meaning_search", "act_plan", "other"] as const;
export type Operation = (typeof OPERATIONS)[number];

export const DEFAULT_MODEL = "gpt-5.4-mini";

const ESTIMATE_MICROS: Record<Operation, number> = {
  facts_generate: 50_000,
  meaning_search: 10_000,
  act_plan: 10_000,
  other: 20_000,
};

const MODEL_ALLOWLIST: Record<Operation, readonly string[]> = {
  facts_generate: [DEFAULT_MODEL],
  meaning_search: [DEFAULT_MODEL],
  act_plan: [DEFAULT_MODEL],
  other: [DEFAULT_MODEL],
};

const RATES_USD_PER_MTOK = {
  vision: { input: 0.20, output: 1.25 },
  text: { input: 0.15, output: 0.60 },
} as const;

export function isOperation(value: string): value is Operation {
  return (OPERATIONS as readonly string[]).includes(value);
}

export function modelFor(operation: Operation): string {
  const configured = Deno.env.get(`CAPIXE_AI_MODEL_${operation.toUpperCase()}`) ||
    Deno.env.get("CAPIXE_AI_MODEL") ||
    DEFAULT_MODEL;
  const allowed = MODEL_ALLOWLIST[operation];
  return allowed.includes(configured) ? configured : allowed[0];
}

export function estimateMicros(operation: Operation): number {
  const envName = `CAPIXE_AI_ESTIMATE_MICROS_${operation.toUpperCase()}`;
  const raw = Deno.env.get(envName);
  if (raw) {
    const parsed = Number.parseInt(raw, 10);
    if (Number.isFinite(parsed) && parsed >= 0) return parsed;
  }
  return ESTIMATE_MICROS[operation];
}

export function kindFor(operation: Operation): "vision" | "text" {
  return operation === "facts_generate" ? "vision" : "text";
}

function usdToMicros(costUsd: unknown): number | null {
  if (costUsd === null || costUsd === undefined || costUsd === "") return null;
  const value = Number(costUsd);
  if (!Number.isFinite(value) || value < 0) return null;
  return Math.round(value * 1_000_000);
}

export function actualCostMicros(
  operation: Operation,
  usage: Record<string, unknown> | null | undefined,
): number {
  const payload = usage && typeof usage === "object" ? usage : {};
  for (const key of ["cost", "total_cost", "cost_usd"]) {
    const converted = usdToMicros(payload[key]);
    if (converted !== null) return converted;
  }
  const inputTokens = Number(payload.prompt_tokens ?? payload.input_tokens ?? 0) || 0;
  const outputTokens = Number(payload.completion_tokens ?? payload.output_tokens ?? 0) || 0;
  const rates = RATES_USD_PER_MTOK[kindFor(operation)];
  const usd = (Math.max(0, inputTokens) * rates.input + Math.max(0, outputTokens) * rates.output) /
    1_000_000;
  if (usd > 0) return Math.round(usd * 1_000_000);
  return estimateMicros(operation);
}
