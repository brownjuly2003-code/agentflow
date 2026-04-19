import { afterEach, describe, expect, it, vi } from "vitest";

import {
  CircuitBreaker,
  CircuitOpenError,
  CircuitState,
} from "../src/circuitBreaker.ts";

afterEach(() => {
  vi.useRealTimers();
});

describe("CircuitBreaker", () => {
  it("starts closed", () => {
    const breaker = new CircuitBreaker();

    expect(breaker.state).toBe(CircuitState.CLOSED);
    expect(() => breaker.beforeCall()).not.toThrow();
  });

  it("opens after the failure threshold", () => {
    const breaker = new CircuitBreaker({ failureThreshold: 3 });

    breaker.recordFailure();
    breaker.recordFailure();
    breaker.recordFailure();

    expect(breaker.state).toBe(CircuitState.OPEN);
    expect(() => breaker.beforeCall()).toThrow(CircuitOpenError);
  });

  it("resets to half-open after timeout", () => {
    vi.useFakeTimers();
    vi.setSystemTime(0);
    const breaker = new CircuitBreaker({ failureThreshold: 1, resetTimeoutMs: 100 });

    breaker.recordFailure();
    vi.setSystemTime(150);
    breaker.beforeCall();

    expect(breaker.state).toBe(CircuitState.HALF_OPEN);
  });

  it("closes after a successful half-open probe", () => {
    vi.useFakeTimers();
    vi.setSystemTime(0);
    const breaker = new CircuitBreaker({ failureThreshold: 1, resetTimeoutMs: 100 });

    breaker.recordFailure();
    vi.setSystemTime(150);
    breaker.beforeCall();
    breaker.recordSuccess();

    expect(breaker.state).toBe(CircuitState.CLOSED);
  });

  it("reopens after a failed half-open probe", () => {
    vi.useFakeTimers();
    vi.setSystemTime(0);
    const breaker = new CircuitBreaker({ failureThreshold: 1, resetTimeoutMs: 100 });

    breaker.recordFailure();
    vi.setSystemTime(150);
    breaker.beforeCall();
    breaker.recordFailure();

    expect(breaker.state).toBe(CircuitState.OPEN);
  });

  it("allows only one probe in half-open state", () => {
    vi.useFakeTimers();
    vi.setSystemTime(0);
    const breaker = new CircuitBreaker({
      failureThreshold: 1,
      resetTimeoutMs: 100,
      halfOpenMaxCalls: 1,
    });

    breaker.recordFailure();
    vi.setSystemTime(150);
    breaker.beforeCall();

    expect(() => breaker.beforeCall()).toThrow(CircuitOpenError);
  });

  it("resets the failure counter after success", () => {
    const breaker = new CircuitBreaker({ failureThreshold: 3 });

    breaker.recordFailure();
    breaker.recordFailure();
    breaker.recordSuccess();
    breaker.recordFailure();
    breaker.recordFailure();

    expect(breaker.state).toBe(CircuitState.CLOSED);
  });
});
