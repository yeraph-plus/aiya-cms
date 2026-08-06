"""Explicit comment kernel registration helpers."""

from inc.kernel.events import EventBus
from inc.kernel.pipeline import PipelineDef, PipelineKey, PipelineRegistry, StepContext

from .events import COMMENT_EVENT_TYPES

COMMENT_SLOT_KEYS: tuple[str, ...] = ("comment.stats",)
COMMENT_PIPELINE_KEYS: tuple[str, ...] = (
    "comment.read",
    "comment.create",
    "comment.update",
    "comment.delete",
    "comment.moderate",
)


async def _noop(_ctx: StepContext) -> None:
    return None


def register_pipelines(registry: PipelineRegistry) -> None:
    for key in COMMENT_PIPELINE_KEYS:
        try:
            registry.get(key)
        except Exception:
            registry.register(
                PipelineDef(
                    key=PipelineKey(key),
                    owner="comment",
                    kind="read" if key == "comment.read" else "write",
                    core=_noop,
                )
            )


def register_events(bus: EventBus) -> None:
    for event_type in (*COMMENT_EVENT_TYPES, "content.deleted", "user.banned"):
        if not bus.is_registered(event_type):
            bus.register(event_type)
