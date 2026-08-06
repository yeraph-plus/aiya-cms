"""Explicit kernel Content pipeline and event registration."""

from inc.kernel.events import EventBus
from inc.kernel.pipeline import PipelineDef, PipelineKey, PipelineRegistry, StepContext

from .events import CONTENT_EVENT_TYPES

CONTENT_PIPELINE_KEYS: tuple[str, ...] = (
    "content.list",
    "content.read",
    "content.create",
    "content.update",
    "content.delete",
)
CONTENT_SLOT_KEYS: tuple[str, ...] = (
    "content.list.before",
    "content.list.after",
    "content.read.after",
    "content.create.before",
    "content.create.after",
    "content.update.before",
    "content.update.after",
    "content.delete.before",
    "content.delete.after",
)


async def _noop(_ctx: StepContext) -> None:
    return None


def register_pipelines(registry: PipelineRegistry) -> None:
    for key in CONTENT_PIPELINE_KEYS:
        try:
            registry.get(key)
        except Exception:
            registry.register(
                PipelineDef(
                    key=PipelineKey(key),
                    owner="content",
                    kind="read" if key in {"content.list", "content.read"} else "write",
                    core=_noop,
                )
            )


def register_events(bus: EventBus) -> None:
    for event_type in CONTENT_EVENT_TYPES:
        if not bus.is_registered(event_type):
            bus.register(event_type)
