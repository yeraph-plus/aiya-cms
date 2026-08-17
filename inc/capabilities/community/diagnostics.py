"""Read-only community consistency diagnostics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from inc.capabilities.community.models import (
    CommunityDiscussion,
    CommunityDiscussionTag,
    CommunityPost,
    CommunitySearchDocument,
    CommunityTag,
)
from inc.capabilities.community.ports import CommunityAuthorPort
from inc.capabilities.community.search import SEARCH_PROFILE
from inc.capabilities.community.types import DiscussionTemplateRegistry
from inc.kernel.db import UoWFactory
from inc.kernel.observability import DiagnosticResult, DiagnosticStatus
from inc.kernel.time import Clock

PENDING_BACKLOG_AGE = timedelta(days=7)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class CommunityDiagnostics:
    key = "community"

    def __init__(
        self,
        *,
        uow_factory: UoWFactory,
        templates: DiscussionTemplateRegistry,
        clock: Clock,
        author_port: CommunityAuthorPort | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._templates = templates
        self._clock = clock
        self._author_port = author_port

    async def run(self) -> list[DiagnosticResult]:
        async with self._uow_factory() as uow:
            discussions = list(
                (await uow.session.execute(select(CommunityDiscussion))).scalars().all()
            )
            posts = list((await uow.session.execute(select(CommunityPost))).scalars().all())
            tags = list((await uow.session.execute(select(CommunityTag))).scalars().all())
            assignments = list(
                (await uow.session.execute(select(CommunityDiscussionTag))).scalars().all()
            )
            documents = list(
                (await uow.session.execute(select(CommunitySearchDocument))).scalars().all()
            )

        discussion_by_id = {row.id: row for row in discussions}
        post_by_id = {post.id: post for post in posts}
        post_by_discussion: dict[object, list[CommunityPost]] = {}
        for post in posts:
            post_by_discussion.setdefault(post.discussion_id, []).append(post)

        unknown_templates = 0
        for discussion in discussions:
            try:
                spec = self._templates.require(discussion.template_key)
                if discussion.schema_version != spec.discussion_data_schema_version:
                    unknown_templates += 1
                spec.validate_discussion_data(dict(discussion.data.payload))
            except Exception:  # noqa: BLE001 - diagnostics only report
                unknown_templates += 1
        for post in posts:
            discussion = discussion_by_id.get(post.discussion_id)
            try:
                if discussion is None:
                    unknown_templates += 1
                    continue
                spec = self._templates.require(discussion.template_key)
                if (
                    post.schema_version != spec.post_data_schema_version
                    or post.body_profile != spec.body_profile
                ):
                    unknown_templates += 1
                spec.validate_post_data(dict(post.data.payload))
            except Exception:  # noqa: BLE001 - diagnostics only report
                unknown_templates += 1

        published_inconsistent = 0
        summary_drift = 0
        for discussion in discussions:
            published = [
                post
                for post in post_by_discussion.get(discussion.id, [])
                if post.status == "published"
            ]
            first = next((post for post in published if post.number == 1), None)
            last = max(
                published,
                key=lambda post: (
                    _utc(post.published_at) or datetime.min.replace(tzinfo=UTC),
                    post.number,
                    str(post.id),
                ),
                default=None,
            )
            expected_replies = max(0, len(published) - (1 if first else 0))
            if discussion.reply_count != expected_replies:
                summary_drift += 1
            if discussion.status == "published" and (
                discussion.published_at is None
                or first is None
                or discussion.first_post_id != first.id
                or last is None
                or discussion.last_post_id != last.id
                or _utc(discussion.last_posted_at) != _utc(last.published_at)
            ):
                published_inconsistent += 1

        tag_by_id = {tag.id: tag for tag in tags}
        hierarchy_invalid = 0
        for tag in tags:
            if tag.parent_id is None:
                continue
            parent = tag_by_id.get(tag.parent_id)
            if (
                tag.kind != "primary"
                or parent is None
                or parent.kind != "primary"
                or parent.parent_id is not None
            ):
                hierarchy_invalid += 1

        assignment_by_discussion: dict[object, list[CommunityDiscussionTag]] = {}
        assignment_invalid = 0
        for assignment in assignments:
            tag = tag_by_id.get(assignment.tag_id)
            if assignment.discussion_id not in discussion_by_id or tag is None:
                assignment_invalid += 1
            else:
                archived_at = _utc(tag.archived_at)
                assigned_at = _utc(assignment.assigned_at)
                if (
                    assigned_at is not None
                    and archived_at is not None
                    and assigned_at > archived_at
                ):
                    assignment_invalid += 1
            assignment_by_discussion.setdefault(assignment.discussion_id, []).append(assignment)

        quantity_invalid = 0
        for discussion in discussions:
            try:
                spec = self._templates.require(discussion.template_key)
            except Exception:  # noqa: BLE001 - already reported above
                continue
            assigned_tags = [
                tag_by_id[assignment.tag_id]
                for assignment in assignment_by_discussion.get(discussion.id, [])
                if assignment.tag_id in tag_by_id
            ]
            primary_count = sum(tag.kind == "primary" for tag in assigned_tags)
            secondary_count = sum(tag.kind == "secondary" for tag in assigned_tags)
            if not spec.min_primary_tags <= primary_count <= spec.max_primary_tags:
                quantity_invalid += 1
            if not spec.min_secondary_tags <= secondary_count <= spec.max_secondary_tags:
                quantity_invalid += 1

        searchable_hidden = 0
        stale_documents = 0
        for document in documents:
            discussion = discussion_by_id.get(document.discussion_id)
            post = post_by_id.get(document.post_id) if document.post_id else None
            source = post if document.document_kind == "post" else discussion
            if (
                discussion is None
                or discussion.status != "published"
                or document.search_profile != SEARCH_PROFILE
                or (
                    document.document_kind == "post"
                    and (post is None or post.status != "published")
                )
            ):
                searchable_hidden += 1
            source_version = source.version if source is not None else 0
            if document.source_version != source_version:
                stale_documents += 1

        now = self._clock.utc_now()
        pending_cutoff = now - PENDING_BACKLOG_AGE
        pending_backlog = sum(
            1
            for row in [*discussions, *posts]
            if row.status == "pending" and (_utc(row.updated_at) or now) <= pending_cutoff
        )

        author_orphans = 0
        author_provider_unavailable = self._author_port is None
        if self._author_port is not None:
            for author_type, author_id in {
                (row.author_type, row.author_id) for row in discussions
            } | {(post.author_type, post.author_id) for post in posts}:
                try:
                    if not await self._author_port.validate(author_type, author_id):
                        author_orphans += 1
                except Exception:  # noqa: BLE001 - dependency diagnostics
                    author_provider_unavailable = True
                    break

        return [
            DiagnosticResult(
                code="community.unknown_template_schema",
                status=DiagnosticStatus.OK if unknown_templates == 0 else DiagnosticStatus.DEGRADED,
                summary=(
                    f"{unknown_templates} discussion/post rows have an unknown template or schema"
                ),
            ),
            DiagnosticResult(
                code="community.discussion_first_post_inconsistent",
                status=DiagnosticStatus.OK
                if published_inconsistent == 0
                else DiagnosticStatus.DEGRADED,
                summary=f"{published_inconsistent} published discussions have an invalid summary",
            ),
            DiagnosticResult(
                code="community.discussion_summary_drift",
                status=DiagnosticStatus.OK if summary_drift == 0 else DiagnosticStatus.DEGRADED,
                summary=f"{summary_drift} discussion summaries have the wrong reply count",
            ),
            DiagnosticResult(
                code="community.tag_hierarchy_invalid",
                status=DiagnosticStatus.OK if hierarchy_invalid == 0 else DiagnosticStatus.DEGRADED,
                summary=f"{hierarchy_invalid} tags violate the one-level hierarchy",
            ),
            DiagnosticResult(
                code="community.tag_quantity_invalid",
                status=DiagnosticStatus.OK if quantity_invalid == 0 else DiagnosticStatus.DEGRADED,
                summary=f"{quantity_invalid} discussions violate template tag limits",
            ),
            DiagnosticResult(
                code="community.tag_assignment_invalid",
                status=DiagnosticStatus.OK
                if assignment_invalid == 0
                else DiagnosticStatus.DEGRADED,
                summary=f"{assignment_invalid} assignments are invalid or were added after archive",
            ),
            DiagnosticResult(
                code="community.search_source_stale",
                status=DiagnosticStatus.OK if stale_documents == 0 else DiagnosticStatus.DEGRADED,
                summary=f"{stale_documents} search documents have stale source versions",
            ),
            DiagnosticResult(
                code="community.hidden_content_searchable",
                status=DiagnosticStatus.OK if searchable_hidden == 0 else DiagnosticStatus.DEGRADED,
                summary=(
                    f"{searchable_hidden} hidden, deleted or unsupported search documents remain"
                ),
            ),
            DiagnosticResult(
                code="community.orphan_author_reference",
                status=DiagnosticStatus.UNAVAILABLE
                if author_provider_unavailable
                else DiagnosticStatus.OK
                if author_orphans == 0
                else DiagnosticStatus.DEGRADED,
                summary=(
                    "author provider unavailable"
                    if author_provider_unavailable
                    else f"{author_orphans} author references cannot be resolved"
                ),
            ),
            DiagnosticResult(
                code="community.pending_backlog",
                status=DiagnosticStatus.OK if pending_backlog == 0 else DiagnosticStatus.DEGRADED,
                summary=(
                    f"{pending_backlog} pending rows are older than {PENDING_BACKLOG_AGE.days} days"
                ),
            ),
        ]
