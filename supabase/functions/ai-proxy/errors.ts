export const ERROR_CODES = {
  unauthenticated: 401,
  account_inactive: 403,
  ai_disabled: 403,
  budget_unavailable: 503,
  budget_exceeded: 429,
  invalid_operation: 400,
  invalid_payload: 400,
  provider_unavailable: 502,
  provider_rate_limited: 429,
  provider_timeout: 504,
  provider_rejected: 502,
  proxy_internal_error: 500,
} as const;

export type ErrorCode = keyof typeof ERROR_CODES;

export type ProxyErrorOptions = {
  providerStatus?: number;
  stalePrevious?: boolean;
  staleChainRetry?: boolean;
};

export class ProxyError extends Error {
  readonly code: ErrorCode;
  readonly status: number;
  readonly resetAt: string;
  readonly providerStatus: number;
  readonly stalePrevious: boolean;
  readonly staleChainRetry: boolean;

  constructor(code: ErrorCode, resetAt = "", options: ProxyErrorOptions = {}) {
    super(code);
    this.code = code;
    this.status = ERROR_CODES[code];
    this.resetAt = resetAt;
    this.providerStatus = Number(options.providerStatus || 0);
    this.stalePrevious = Boolean(options.stalePrevious);
    this.staleChainRetry = Boolean(options.staleChainRetry);
  }
}

export function jsonError(
  code: ErrorCode,
  resetAt = "",
  extra: { stale_chain_retry?: boolean } = {},
): Response {
  return new Response(
    JSON.stringify({
      ok: false,
      error: {
        code,
        ...(resetAt ? { reset_at: resetAt } : {}),
        ...(extra.stale_chain_retry ? { stale_chain_retry: true } : {}),
      },
    }),
    {
      status: ERROR_CODES[code],
      headers: { "Content-Type": "application/json" },
    },
  );
}

export function mapBudgetException(message: string, hint = ""): ProxyError {
  const text = `${message} ${hint}`.toLowerCase();
  if (text.includes("ai_not_authenticated")) return new ProxyError("unauthenticated");
  if (text.includes("ai_account_inactive")) return new ProxyError("account_inactive", hint);
  if (text.includes("ai_not_allowed")) return new ProxyError("ai_disabled", hint);
  if (text.includes("ai_budget_exceeded")) return new ProxyError("budget_exceeded", hint);
  return new ProxyError("budget_unavailable", hint);
}
