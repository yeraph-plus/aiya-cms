"""Interaction command boundaries that do not require a database."""

from typing import cast
from uuid import uuid4

import pytest
from pydantic import ValidationError

from inc.kernel.db import UoWExecutor
from inc.kernel.errors import COMMON_404, AppError
from inc.kernel.errors.registry import ErrorRegistry, register_error_codes
from inc.kernel.events import fresh_event_bus
from inc.kernel.security import Principal
from inc.modules.interaction import InteractionService, RatingWrite


@pytest.mark.asyncio
async def test_interaction_rejects_missing_content_target() -> None:
    if not ErrorRegistry.has(COMMON_404.code):
        register_error_codes(COMMON_404)
    service = InteractionService(
        cast(UoWExecutor, object()),
        target_exists=lambda _type_name, _target_id: False,
        event_bus=fresh_event_bus(),
    )
    with pytest.raises(AppError) as error:
        await service.like(uuid4(), Principal(id=uuid4(), username="reader"))
    assert error.value.code == COMMON_404


def test_rating_is_limited_to_one_to_five() -> None:
    assert RatingWrite(score=1).score == 1
    assert RatingWrite(score=5).score == 5
    with pytest.raises(ValidationError):
        RatingWrite(score=0)
    with pytest.raises(ValidationError):
        RatingWrite(score=6)
