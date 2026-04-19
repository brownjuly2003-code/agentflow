import { describe, expect, it } from "vitest";

import {
  RETRYABLE_STATUS,
  RetryPolicy,
  isRetryableMethod,
} from "../src/retry.ts";

describe("RetryPolicy", () => {
  it("computes exponential backoff", () => {
    const policy = new RetryPolicy({
      maxAttempts: 5,
      initialDelayMs: 100,
      jitterFactor: 0,
    });

    expect(policy.computeDelay(0)).toBe(100);
    expect(policy.computeDelay(1)).toBe(200);
    expect(policy.computeDelay(2)).toBe(400);
    expect(policy.computeDelay(3)).toBe(800);
  });

  it("respects retry-after and caps it at max delay", () => {
    const policy = new RetryPolicy({
      initialDelayMs: 100,
      maxDelayMs: 5_000,
      jitterFactor: 0,
    });

    expect(policy.computeDelay(0, 3_000)).toBe(3_000);
    expect(policy.computeDelay(0, 999_000)).toBe(5_000);
  });

  it("caps exponential delay at max delay", () => {
    const policy = new RetryPolicy({
      initialDelayMs: 100,
      maxDelayMs: 1_000,
      jitterFactor: 0,
    });

    expect(policy.computeDelay(10)).toBe(1_000);
  });

  it("keeps jittered delays within bounds", () => {
    const policy = new RetryPolicy({
      initialDelayMs: 1_000,
      jitterFactor: 0.5,
    });
    const samples = Array.from({ length: 100 }, () => policy.computeDelay(0));

    expect(samples.every((sample) => sample >= 500 && sample <= 1_500)).toBe(true);
  });

  it("treats only idempotent methods as retryable by default", () => {
    expect(isRetryableMethod("GET")).toBe(true);
    expect(isRetryableMethod("HEAD")).toBe(true);
    expect(isRetryableMethod("PUT")).toBe(true);
    expect(isRetryableMethod("DELETE")).toBe(true);
    expect(isRetryableMethod("POST")).toBe(false);
  });

  it("exports the expected retryable statuses", () => {
    expect(RETRYABLE_STATUS.has(429)).toBe(true);
    expect(RETRYABLE_STATUS.has(503)).toBe(true);
    expect(RETRYABLE_STATUS.has(504)).toBe(true);
    expect(RETRYABLE_STATUS.has(200)).toBe(false);
    expect(RETRYABLE_STATUS.has(404)).toBe(false);
  });
});
