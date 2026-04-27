class AgentFlowError(Exception):
    pass


class AuthError(AgentFlowError):
    pass


class PermissionDeniedError(AgentFlowError):
    pass


class RateLimitError(AgentFlowError):
    def __init__(self, message: str, retry_after: int = 0):
        super().__init__(message)
        self.retry_after = retry_after


class DataFreshnessError(AgentFlowError):
    pass


class EntityNotFoundError(AgentFlowError):
    def __init__(self, entity_type: str, entity_id: str, message: str | None = None):
        super().__init__(message or f"{entity_type}/{entity_id} not found")
        self.entity_type = entity_type
        self.entity_id = entity_id
