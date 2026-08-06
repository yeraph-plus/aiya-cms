"""Public kernel imports and compatibility version are intentionally frozen."""

import inspect

from inc.kernel import KERNEL_API_VERSION
from inc.kernel.content import ContentCreate, ContentRead, ContentService
from inc.kernel.errors import AppError, ErrorCode, COMMON_404
from inc.kernel.events import Event, EventBus
from inc.kernel.pipeline import PipelineKey
from inc.kernel.rbac import CapabilityChecker


def test_kernel_version_and_public_symbols() -> None:
    assert KERNEL_API_VERSION == "0.1.0"
    assert issubclass(AppError, Exception)
    assert isinstance(COMMON_404, ErrorCode)
    assert inspect.isclass(Event)
    assert inspect.isclass(EventBus)
    assert inspect.isclass(PipelineKey)
    assert inspect.isclass(CapabilityChecker)
    assert inspect.isclass(ContentService)
    assert ContentCreate.model_fields["title"].is_required()
    assert "id" in ContentRead.model_fields
