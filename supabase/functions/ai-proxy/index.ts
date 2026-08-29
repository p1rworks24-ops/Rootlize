import {
  finalizeBudget,
  releaseBudget,
  requireUser,
  reserveBudget,
  usageStatus,
  userClient,
} from "./budget.ts";
import { jsonError, ProxyError } from "./errors.ts";
import { runOperation } from "./operations.ts";
import { actualCostMicros, estimateMicros, modelFor } from "./pricing.ts";
import { validateRequest } from "./validate.ts";

function hashUser(userId: string): string {
  // Short, non-reversible-enough label for logs. Not a secret.
  return userId.replace(/-/g, "").slice(0, 8);
}

function logSafe(fields: Record<string, unknown>): void {
  console.log(JSON.stringify(fields));
}

Deno.serve(async (req) => {
  const started = Date.now();
  let requestId = "";
  let operation = "";
  let reservationId = "";
  let userHash = "";
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204 });
  }
  if (req.method !== "POST") {
    return jsonError("invalid_operation");
  }

  try {
    const { token, client } = userClient(req);
    const userId = await requireUser(client, token);
    userHash = hashUser(userId);

    let body: unknown;
    try {
      body = await req.json();
    } catch {
      throw new ProxyError("invalid_payload");
    }
    const validated = validateRequest(body);
    requestId = validated.requestId;
    operation = validated.operation;
    const model = modelFor(validated.operation);
    const estimated = estimateMicros(validated.operation);

    reservationId = await reserveBudget(client, {
      estimatedCostMicros: estimated,
      operation: validated.operation,
      model,
      requestId,
    });

    let providerResult: { result: unknown; usage: Record<string, unknown>; model: string; responseId?: string; staleChainRetry?: boolean };
    try {
      providerResult = await runOperation(validated);
    } catch (error) {
      await releaseBudget(client, reservationId);
      reservationId = "";
      throw error;
    }

    const actual = actualCostMicros(validated.operation, providerResult.usage);
    await finalizeBudget(client, reservationId, actual);
    reservationId = "";
    const usage = await usageStatus(client);
    const previousPresent = validated.operation === "act_plan"
      && Boolean(validated.payload.previous_response_id);
    logSafe({
      request_id: requestId,
      operation,
      user: userHash,
      model,
      status: "ok",
      latency_ms: Date.now() - started,
      estimated_cost: estimated,
      actual_cost: actual,
      previous_response_id_present: previousPresent,
      stale_chain_retry: Boolean(providerResult.staleChainRetry),
    });
    return new Response(
      JSON.stringify({
        ok: true,
        request_id: requestId,
        result: providerResult.result,
        response_id: providerResult.responseId || "",
        stale_chain_retry: Boolean(providerResult.staleChainRetry),
        usage,
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  } catch (error) {
    const proxyError = error instanceof ProxyError ? error : new ProxyError("proxy_internal_error");
    if (reservationId) {
      try {
        const recovered = userClient(req);
        await releaseBudget(recovered.client, reservationId);
      } catch {
        // already logged inside releaseBudget
      }
    }
    logSafe({
      request_id: requestId || "unknown",
      operation: operation || "unknown",
      user: userHash || "none",
      status: "error",
      latency_ms: Date.now() - started,
      error_code: proxyError.code,
      stale_chain_retry: Boolean(proxyError.staleChainRetry),
    });
    return jsonError(proxyError.code, proxyError.resetAt, {
      stale_chain_retry: proxyError.staleChainRetry || undefined,
    });
  }
});
