class PricingError(Exception):
    """Base error for the pricing decision service."""

    def __init__(self, message: str, *, reason: str = "error", status_code: int = 500):
        super().__init__(message)
        self.message = message
        self.reason = reason
        self.status_code = status_code


class ValidationFailedError(PricingError):
    def __init__(self, message: str, *, reason: str = "validation_error"):
        super().__init__(message, reason=reason, status_code=400)


class SkuNotFoundError(PricingError):
    def __init__(self, sku: str):
        super().__init__(f"Unknown SKU: {sku}", reason="unknown_sku", status_code=404)
        self.sku = sku


class FallbackError(PricingError):
    """Raised inside a stage so the orchestrator can degrade, not abort."""

    def __init__(self, message: str, *, reason: str, stage: str):
        super().__init__(message, reason=reason, status_code=200)
        self.stage = stage
