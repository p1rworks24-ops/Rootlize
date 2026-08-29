import { ProxyError } from "./errors.ts";
import {
  ACT_PLAN_PROMPT,
  FACT_PROMPT,
  FACTS_USER_PREFIX,
  PLAN_JSON_SCHEMA,
  SEARCH_PROMPT,
  SEARCH_USER_PREFIX,
} from "./prompts.ts";
import { completeChat, completeResponse, isStalePreviousResponseError } from "./openai.ts";
import { modelFor } from "./pricing.ts";
import { factSchema, searchSchema } from "./schemas.ts";
import type { ActPlanPayload, FactsPayload, MeaningPayload, ValidatedRequest } from "./validate.ts";

function jsonSchemaFormat(name: string, schema: Record<string, unknown>) {
  return {
    type: "json_schema",
    json_schema: { name, strict: true, schema },
  };
}

export async function runOperation(request: ValidatedRequest): Promise<{ result: unknown; usage: Record<string, unknown>; model: string; responseId?: string; staleChainRetry?: boolean }> {
  const model = modelFor(request.operation);
  if (request.operation === "facts_generate") {
    return runFacts(model, request.payload);
  }
  if (request.operation === "meaning_search") {
    return runMeaning(model, request.payload);
  }
  return runActPlan(model, request.payload);
}

async function runFacts(model: string, payload: FactsPayload) {
  const content: Record<string, unknown>[] = [
    { type: "text", text: `${FACTS_USER_PREFIX} image_id ${payload.image_id}.` },
  ];
  for (const view of payload.views) {
    content.push({ type: "text", text: view.label });
    content.push({
      type: "image_url",
      image_url: {
        url: `data:image/jpeg;base64,${view.image_jpeg_b64}`,
        detail: "high",
      },
    });
  }
  const completed = await completeChat({
    model,
    temperature: 0,
    messages: [
      { role: "system", content: FACT_PROMPT },
      { role: "user", content },
    ],
    response_format: jsonSchemaFormat("image_facts", factSchema([payload.image_id])),
  });
  const parsed = completed.content as { results?: unknown[] };
  const record = Array.isArray(parsed?.results) ? parsed.results[0] : null;
  if (!record || typeof record !== "object") {
    return { result: { image_id: payload.image_id, unknown_reason: "malformed" }, usage: completed.usage, model };
  }
  return { result: record, usage: completed.usage, model };
}

async function runMeaning(model: string, payload: MeaningPayload) {
  const imageIds = payload.items.map((item) => item.image_id);
  const docs = payload.items.map((item) => item.document).join("\n\n");
  const completed = await completeChat({
    model,
    temperature: 0,
    messages: [
      { role: "system", content: SEARCH_PROMPT },
      {
        role: "user",
        content: `Query: ${payload.query}\n\n${SEARCH_USER_PREFIX}\n\n${docs}`,
      },
    ],
    response_format: jsonSchemaFormat("db_sot_relevance", searchSchema(imageIds)),
  });
  const parsed = completed.content as { results?: unknown };
  if (!parsed || typeof parsed !== "object" || !Array.isArray(parsed.results)) {
    return { result: { results: [] }, usage: completed.usage, model };
  }
  return { result: { results: parsed.results }, usage: completed.usage, model };
}

async function runActPlan(model: string, payload: ActPlanPayload) {
  const body = {
    model,
    instructions: ACT_PLAN_PROMPT,
    input: payload.user_prompt,
    store: true,
    truncation: "auto",
    temperature: 0,
    text: {
      format: {
        type: "json_schema",
        name: "capixe_act_plan",
        strict: true,
        schema: PLAN_JSON_SCHEMA as unknown as Record<string, unknown>,
      },
    },
    ...(payload.previous_response_id ? { previous_response_id: payload.previous_response_id } : {}),
  };
  let completed;
  let staleChainRetry = false;
  try {
    completed = await completeResponse(body);
  } catch (error) {
    if (!payload.previous_response_id || !isStalePreviousResponseError(error)) throw error;
    const { previous_response_id: _unused, ...fresh } = body;
    void _unused;
    try {
      completed = await completeResponse(fresh);
      staleChainRetry = true;
    } catch {
      if (error instanceof ProxyError) {
        throw new ProxyError(error.code, error.resetAt, {
          providerStatus: error.providerStatus,
          stalePrevious: true,
          staleChainRetry: true,
        });
      }
      throw error;
    }
  }
  const parsed = completed.content;
  if (!parsed || typeof parsed !== "object") {
    throw new ProxyError("invalid_payload");
  }
  return {
    result: parsed,
    usage: completed.usage,
    model,
    responseId: completed.responseId,
    staleChainRetry,
  };
}
