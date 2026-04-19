import { AgentFlowError } from "./exceptions.js";

export enum CircuitState {
  CLOSED = "closed",
  OPEN = "open",
  HALF_OPEN = "half_open",
}

export class CircuitOpenError extends AgentFlowError {
  constructor(message = "circuit is open") {
    super(message);
    this.name = "CircuitOpenError";
  }
}

export interface CircuitBreakerOptions {
  failureThreshold?: number;
  resetTimeoutMs?: number;
  halfOpenMaxCalls?: number;
}

export class CircuitBreaker {
  readonly failureThreshold: number;
  readonly resetTimeoutMs: number;
  readonly halfOpenMaxCalls: number;
  private _state = CircuitState.CLOSED;
  private failureCount = 0;
  private openedAt = 0;
  private halfOpenCalls = 0;

  constructor(options: CircuitBreakerOptions = {}) {
    this.failureThreshold = options.failureThreshold ?? 5;
    this.resetTimeoutMs = options.resetTimeoutMs ?? 30_000;
    this.halfOpenMaxCalls = options.halfOpenMaxCalls ?? 1;
  }

  beforeCall(): void {
    if (this._state === CircuitState.OPEN) {
      if (Date.now() - this.openedAt >= this.resetTimeoutMs) {
        this._state = CircuitState.HALF_OPEN;
        this.halfOpenCalls = 0;
      } else {
        throw new CircuitOpenError("circuit is open");
      }
    }
    if (this._state === CircuitState.HALF_OPEN) {
      if (this.halfOpenCalls >= this.halfOpenMaxCalls) {
        throw new CircuitOpenError("circuit is half-open, probe in flight");
      }
      this.halfOpenCalls += 1;
    }
  }

  recordSuccess(): void {
    this._state = CircuitState.CLOSED;
    this.failureCount = 0;
    this.halfOpenCalls = 0;
  }

  recordFailure(): void {
    if (this._state === CircuitState.HALF_OPEN) {
      this._state = CircuitState.OPEN;
      this.openedAt = Date.now();
      this.halfOpenCalls = 0;
      return;
    }
    this.failureCount += 1;
    if (this.failureCount >= this.failureThreshold) {
      this._state = CircuitState.OPEN;
      this.openedAt = Date.now();
      this.halfOpenCalls = 0;
    }
  }

  get state(): CircuitState {
    return this._state;
  }
}
