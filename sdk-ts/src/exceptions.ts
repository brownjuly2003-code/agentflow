export class AgentFlowError extends Error {
  readonly statusCode?: number;

  constructor(message: string, statusCode?: number) {
    super(message);
    this.name = "AgentFlowError";
    this.statusCode = statusCode;
  }
}

export class AuthError extends AgentFlowError {
  constructor(message = "Unauthorized") {
    super(message, 401);
    this.name = "AuthError";
  }
}

export class PermissionDeniedError extends AgentFlowError {
  constructor(message = "Forbidden") {
    super(message, 403);
    this.name = "PermissionDeniedError";
  }
}

export class RateLimitError extends AgentFlowError {
  readonly retryAfter: number;

  constructor(message = "Rate limit exceeded", retryAfter = 0) {
    super(message, 429);
    this.name = "RateLimitError";
    this.retryAfter = retryAfter;
  }
}

export class DataFreshnessError extends AgentFlowError {
  constructor(message: string) {
    super(message);
    this.name = "DataFreshnessError";
  }
}

export class EntityNotFoundError extends AgentFlowError {
  readonly entityType: string;
  readonly entityId: string;

  constructor(entityType: string, entityId: string, message?: string) {
    super(message ?? `${entityType}/${entityId} not found`, 404);
    this.name = "EntityNotFoundError";
    this.entityType = entityType;
    this.entityId = entityId;
  }
}
