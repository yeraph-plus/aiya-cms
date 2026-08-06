"""Explicit taxonomy kernel registration helpers."""

from inc.kernel.events import EventBus
from inc.kernel.pipeline import PipelineDef, PipelineKey, PipelineRegistry, StepContext

from .events import TAXONOMY_EVENT_TYPES

TAXONOMY_SLOT_KEYS: tuple[str, ...] = ("taxonomy.term_filter", "taxonomy.content_terms")
TAXONOMY_PIPELINE_KEYS: tuple[str, ...] = (
    "term.create",
    "term.update",
    "term.delete",
    "term.assign",
)


async def _noop(_ctx: StepContext) -> None:
    return None


def register_pipelines(registry: PipelineRegistry) -> None:
    for key in TAXONOMY_PIPELINE_KEYS:
        try:
            registry.get(key)
        except Exception:
            registry.register(
                PipelineDef(key=PipelineKey(key), owner="taxonomy", kind="write", core=_noop)
            )


def register_events(bus: EventBus) -> None:
    for event_type in (*TAXONOMY_EVENT_TYPES, "content.deleted"):
        if not bus.is_registered(event_type):
            bus.register(event_type)
