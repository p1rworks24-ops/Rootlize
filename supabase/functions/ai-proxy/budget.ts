import { createClient, type SupabaseClient } from "https://esm.sh/@supabase/supabase-js@2.49.1";
import { mapBudgetException, ProxyError } from "./errors.ts";

export type UsageEnvelope = {
  used_percent: number;
  remaining_percent: number;
  reset_at: string;
  limit_reached: boolean;
};

function hintFrom(error: { message?: string; hint?: string } | null): string {
  return String(error?.hint || "").slice(0, 32);
}

function raiseBudget(error: { message?: string; hint?: string } | null): never {
  throw mapBudgetException(error?.message || "budget_unavailable", hintFrom(error));
}

export function userClient(req: Request): { token: string; client: SupabaseClient } {
  const auth = req.headers.get("Authorization") || "";
  if (!auth.toLowerCase().startsWith("bearer ")) {
    throw new ProxyError("unauthenticated");
  }
  const token = auth.slice(7).trim();
  if (!token) throw new ProxyError("unauthenticated");
  const url = Deno.env.get("SUPABASE_URL") || "";
  const anon = Deno.env.get("SUPABASE_ANON_KEY") || "";
  if (!url || !anon) throw new ProxyError("proxy_internal_error");
  const client = createClient(url, anon, {
    global: { headers: { Authorization: `Bearer ${token}` } },
    auth: { persistSession: false, autoRefreshToken: false },
  });
  return { token, client };
}

export async function requireUser(client: SupabaseClient, token: string): Promise<string> {
  const { data, error } = await client.auth.getUser(token);
  if (error || !data.user?.id) throw new ProxyError("unauthenticated");
  return data.user.id;
}

export async function reserveBudget(
  client: SupabaseClient,
  args: {
    estimatedCostMicros: number;
    operation: string;
    model: string;
    requestId: string;
  },
): Promise<string> {
  const { data, error } = await client.rpc("reserve_ai_budget", {
    p_estimated_cost_micros: args.estimatedCostMicros,
    p_operation: args.operation,
    p_provider: "openai",
    p_model: args.model,
    p_request_id: args.requestId,
  });
  if (error) raiseBudget(error);
  const reservationId = String((data as { reservation_id?: string } | null)?.reservation_id || "");
  if (!reservationId) throw new ProxyError("budget_unavailable");
  return reservationId;
}

export async function finalizeBudget(
  client: SupabaseClient,
  reservationId: string,
  actualCostMicros: number,
): Promise<void> {
  const { error } = await client.rpc("finalize_ai_usage", {
    p_reservation_id: reservationId,
    p_actual_cost_micros: actualCostMicros,
  });
  if (error) raiseBudget(error);
}

export async function releaseBudget(client: SupabaseClient, reservationId: string): Promise<void> {
  const { error } = await client.rpc("release_ai_reservation", {
    p_reservation_id: reservationId,
  });
  if (error) {
    // Release is best-effort after provider failure.
    console.log(JSON.stringify({
      event: "release_failed",
      error_code: "budget_unavailable",
    }));
  }
}

export async function usageStatus(client: SupabaseClient): Promise<UsageEnvelope> {
  const { data, error } = await client.rpc("get_ai_usage_status");
  if (error) raiseBudget(error);
  const payload = (data && typeof data === "object") ? data as Record<string, unknown> : {};
  const used = Number(payload.used_percent ?? 0) || 0;
  const remaining = payload.remaining_percent === undefined
    ? Math.max(0, 100 - used)
    : Number(payload.remaining_percent) || 0;
  return {
    used_percent: used,
    remaining_percent: remaining,
    reset_at: String(payload.reset_at || "").slice(0, 10),
    limit_reached: Boolean(payload.limit_reached),
  };
}
