"""FastAPI-facing current-principal boundary."""

from inc.kernel.security import Principal, get_current_principal

__all__ = ["Principal", "get_current_principal"]
