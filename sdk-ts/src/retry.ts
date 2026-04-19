export const RETRYABLE_STATUS = new Set([429, 502, 503, 504]);

const DEFAULT_MAX_ATTEMPTS = 3;
const DEFAULT_INITIAL_DELAY_MS = 250;
const DEFAULT_MAX_DELAY_MS = 30_000;
const DEFAULT_JITTER_FACTOR = 0.3;

export interface RetryPolicyOptions {
  maxAttempts?: number;
  initialDelayMs?: number;
  maxDelayMs?: number;
  jitterFactor?: number;
}

export class RetryPolicy {
  readonly maxAttempts: number;
  readonly initialDelayMs: number;
  readonly maxDelayMs: number;
  readonly jitterFactor: number;

  constructor(options: RetryPolicyOptions = {}) {
    this.maxAttempts = options.maxAttempts ?? DEFAULT_MAX_ATTEMPTS;
    this.initialDelayMs = options.initialDelayMs ?? DEFAULT_INITIAL_DELAY_MS;
    this.maxDelayMs = options.maxDelayMs ?? DEFAULT_MAX_DELAY_MS;
    this.jitterFactor = options.jitterFactor ?? DEFAULT_JITTER_FACTOR;
  }

  computeDelay(attempt: number, retryAfterMs?: number): number {
    if (retryAfterMs != null) {
      return Math.min(Math.max(retryAfterMs, 0), this.maxDelayMs);
    }
    const base = Math.min(this.initialDelayMs * 2 ** attempt, this.maxDelayMs);
    if (this.jitterFactor === 0) {
      return base;
    }
    const jitterRange = base * this.jitterFactor;
    const jitter = (Math.random() * jitterRange * 2) - jitterRange;
    return Math.max(0, Math.min(base + jitter, this.maxDelayMs));
  }
}

export function isRetryableMethod(
  method: string,
  headers?: HeadersInit,
): boolean {
  const normalizedMethod = method.toUpperCase();
  if (["GET", "HEAD", "PUT", "DELETE", "OPTIONS"].includes(normalizedMethod)) {
    return true;
  }
  if (normalizedMethod !== "POST" || headers == null) {
    return false;
  }
  if (headers instanceof Headers) {
    return headers.has("Idempotency-Key");
  }
  if (Array.isArray(headers)) {
    return headers.some(([key]) => key.toLowerCase() === "idempotency-key");
  }
  return Object.keys(headers).some((key) => key.toLowerCase() === "idempotency-key");
}
