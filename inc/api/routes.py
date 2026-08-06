"""Versioned HTTP routes for health, auth and kernel read APIs."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel

from inc.kernel.audit import AuditLogRead, AuditQuery, AuditService
from inc.kernel.auth import (
    AuthMe,
    AuthRegistrationPolicy,
    AuthService,
    ForgotPasswordRequest,
    LoginRequest,
    PasswordResetMailContext,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenPair,
)
from inc.kernel.comment import (
    CommentCreate,
    CommentModerationQuery,
    CommentRead,
    CommentService,
    CommentStats,
    CommentStatus,
    CommentThread,
    CommentThreadQuery,
    CommentUpdate,
    ModerateRequest,
)
from inc.kernel.content import (
    ContentCreate,
    ContentListQuery,
    ContentRead,
    ContentService,
    ContentTypeRead,
    ContentUpdate,
)
from inc.kernel.db import Page
from inc.kernel.errors import AppError, ErrorResponse
from inc.kernel.identity import (
    IdentityService,
    UserAdminRead,
    UserAdminUpdate,
    UserQuery,
    UserRead,
)
from inc.kernel.mail import MailService
from inc.kernel.rbac import (
    PermissionRead,
    RBACService,
    RoleAssign,
    RoleRead,
    UserRoleSet,
    require_any_capability,
    require_capability,
)
from inc.kernel.security import AUTH_003, Principal
from inc.kernel.settings import (
    SettingGroupRead,
    SettingPatch,
    SettingsService,
)
from inc.kernel.tasks import TaskInstanceRead, TaskQuery, TaskScheduler, TaskState
from inc.kernel.taxonomy import (
    TermAssign,
    TermCreate,
    TermListQuery,
    TermRead,
    TermService,
    TermUpdate,
)
from inc.modules.interaction import (
    InteractionQuery,
    InteractionRead,
    InteractionService,
    RatingWrite,
)

from .deps import (
    get_audit,
    get_auth,
    get_comments,
    get_content,
    get_identity,
    get_interactions,
    get_mail,
    get_rbac,
    get_runtime_settings,
    get_scheduler,
    get_taxonomy,
    optional_principal,
    require_authenticated,
)


class ContentDetailResponse(BaseModel):
    content: ContentRead
    terms: list[TermRead]
    comment_stats: CommentStats


class DashboardSummary(BaseModel):
    users_total: int | None = None
    contents_total: int | None = None
    comments_pending: int | None = None
    tasks_active: int | None = None


class PublicSettingsRead(BaseModel):
    site_profile: dict[str, Any]


_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (400, 401, 403, 404, 409, 422, 429, 500, 504)
}
router = APIRouter(prefix="/api/v1", responses=_ERROR_RESPONSES)
auth_router = APIRouter(prefix="/auth", tags=["auth"], responses=_ERROR_RESPONSES)
public_router = APIRouter(prefix="/public", tags=["public"], responses=_ERROR_RESPONSES)


@router.get("/health", tags=["system"])
async def health(request: Request) -> dict[str, Any]:
    container = request.app.state.container
    postgres = "ok"
    try:
        from sqlalchemy import select

        async with container.database.engine.connect() as connection:
            await connection.scalar(select(1))
    except Exception:
        postgres = "down"
    redis = "ok"
    checker = getattr(container.cache, "health", None)
    if checker is not None:
        try:
            if not await checker():
                redis = "down"
        except Exception:
            redis = "down"
    dependencies = {"postgres": postgres, "redis": redis}
    return {
        "status": "ok" if all(value == "ok" for value in dependencies.values()) else "degraded",
        "environment": container.settings.env,
        "version": "0.1.0",
        "dependencies": dependencies,
    }


@router.get(
    "/dashboard",
    response_model=DashboardSummary,
    tags=["dashboard"],
)
async def dashboard(
    principal: Principal = Depends(require_authenticated),  # noqa: B008
    identity: IdentityService = Depends(get_identity),  # noqa: B008
    content: ContentService = Depends(get_content),  # noqa: B008
    comments: CommentService = Depends(get_comments),  # noqa: B008
    scheduler: TaskScheduler = Depends(get_scheduler),  # noqa: B008
) -> DashboardSummary:
    summary = DashboardSummary()
    if "user:read_any" in principal.capabilities:
        summary.users_total = (await identity.list_users(UserQuery(size=1))).total
    if "content:update_any" in principal.capabilities:
        summary.contents_total = (
            await content.list("post", ContentListQuery(size=1), principal)
        ).total
    if "comment:moderate" in principal.capabilities:
        summary.comments_pending = (
            await comments.list_moderation(
                CommentModerationQuery(status=CommentStatus.PENDING, size=1)
            )
        ).total
    if "task:manage" in principal.capabilities:
        pending = (await scheduler.list_instances(TaskQuery(state=TaskState.PENDING, size=1))).total
        running = (await scheduler.list_instances(TaskQuery(state=TaskState.RUNNING, size=1))).total
        summary.tasks_active = pending + running
    return summary


@router.get(
    "/content-types",
    response_model=list[ContentTypeRead],
    dependencies=[Depends(require_any_capability(("content:create", "content:update_any")))],
    tags=["content"],
)
async def list_content_types(
    content: ContentService = Depends(get_content),  # noqa: B008
) -> list[ContentTypeRead]:
    return await content.list_types()


@router.get("/contents/{type_name}", response_model=Page[ContentRead], tags=["content"])
async def list_contents(
    type_name: str,
    query: ContentListQuery = Depends(),  # noqa: B008
    principal: Principal = Depends(optional_principal),  # noqa: B008
    content: ContentService = Depends(get_content),  # noqa: B008
) -> Page[ContentRead]:
    return await content.list(type_name, query, principal)


@router.get("/contents/{type_name}/{slug}", response_model=ContentDetailResponse, tags=["content"])
async def get_content_detail(
    type_name: str,
    slug: str,
    principal: Principal = Depends(optional_principal),  # noqa: B008
    content: ContentService = Depends(get_content),  # noqa: B008
    taxonomy: TermService = Depends(get_taxonomy),  # noqa: B008
    comments: CommentService = Depends(get_comments),  # noqa: B008
) -> ContentDetailResponse:
    item = await content.get_by_slug(type_name, slug, principal)
    terms = (await taxonomy.terms_for_contents([item.id])).get(item.id)
    stats = (await comments.stats_for_targets(type_name, [item.id])).get(item.id)
    return ContentDetailResponse(
        content=item,
        terms=[] if terms is None else terms.terms,
        comment_stats=CommentStats() if stats is None else stats,
    )


@router.post(
    "/contents/{type_name}",
    response_model=ContentRead,
    status_code=status.HTTP_201_CREATED,
    tags=["content"],
)
async def create_content(
    type_name: str,
    payload: ContentCreate,
    principal: Principal = Depends(require_authenticated),  # noqa: B008
    content: ContentService = Depends(get_content),  # noqa: B008
) -> ContentRead:
    return await content.create(type_name, payload, principal)


@router.patch("/contents/{type_name}/{content_id}", response_model=ContentRead, tags=["content"])
async def update_content(
    type_name: str,
    content_id: UUID,
    payload: ContentUpdate,
    principal: Principal = Depends(require_authenticated),  # noqa: B008
    content: ContentService = Depends(get_content),  # noqa: B008
) -> ContentRead:
    return await content.update(type_name, content_id, payload, principal)


@router.post(
    "/contents/{type_name}/{content_id}/{action}", response_model=ContentRead, tags=["content"]
)
async def transition_content(
    type_name: str,
    content_id: UUID,
    action: str,
    principal: Principal = Depends(require_authenticated),  # noqa: B008
    content: ContentService = Depends(get_content),  # noqa: B008
) -> ContentRead:
    return await content.transition(type_name, content_id, action, principal)


@router.delete(
    "/contents/{type_name}/{content_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["content"]
)
async def delete_content(
    type_name: str,
    content_id: UUID,
    purge: bool = False,
    principal: Principal = Depends(require_authenticated),  # noqa: B008
    content: ContentService = Depends(get_content),  # noqa: B008
) -> None:
    await content.transition(type_name, content_id, "purge" if purge else "trash", principal)


@router.get("/terms/{type_name}", response_model=Page[TermRead], tags=["taxonomy"])
async def list_terms(
    type_name: str,
    query: TermListQuery = Depends(),  # noqa: B008
    taxonomy: TermService = Depends(get_taxonomy),  # noqa: B008
) -> Page[TermRead]:
    return await taxonomy.list(type_name, query)


@router.get("/terms/{type_name}/{term_id}", response_model=TermRead, tags=["taxonomy"])
async def get_term(
    type_name: str,
    term_id: UUID,
    taxonomy: TermService = Depends(get_taxonomy),  # noqa: B008
) -> TermRead:
    return await taxonomy.get(type_name, term_id)


@router.post(
    "/terms/{type_name}",
    response_model=TermRead,
    status_code=status.HTTP_201_CREATED,
    tags=["taxonomy"],
)
async def create_term(
    type_name: str,
    payload: TermCreate,
    principal: Principal = Depends(require_authenticated),  # noqa: B008
    taxonomy: TermService = Depends(get_taxonomy),  # noqa: B008
) -> TermRead:
    return await taxonomy.create(type_name, payload, principal)


@router.patch("/terms/{type_name}/{term_id}", response_model=TermRead, tags=["taxonomy"])
async def update_term(
    type_name: str,
    term_id: UUID,
    payload: TermUpdate,
    principal: Principal = Depends(require_authenticated),  # noqa: B008
    taxonomy: TermService = Depends(get_taxonomy),  # noqa: B008
) -> TermRead:
    return await taxonomy.update(type_name, term_id, payload, principal)


@router.delete(
    "/terms/{type_name}/{term_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["taxonomy"]
)
async def delete_term(
    type_name: str,
    term_id: UUID,
    principal: Principal = Depends(require_authenticated),  # noqa: B008
    taxonomy: TermService = Depends(get_taxonomy),  # noqa: B008
) -> None:
    await taxonomy.delete(type_name, term_id, principal)


@router.put(
    "/contents/{type_name}/{content_id}/terms", response_model=list[TermRead], tags=["taxonomy"]
)
async def assign_terms(
    type_name: str,
    content_id: UUID,
    payload: TermAssign,
    principal: Principal = Depends(require_authenticated),  # noqa: B008
    taxonomy: TermService = Depends(get_taxonomy),  # noqa: B008
) -> list[TermRead]:
    return await taxonomy.assign(type_name, content_id, payload, principal)


@router.get("/comments", response_model=Page[CommentThread], tags=["comment"])
async def list_comments(
    target_type: str,
    target_id: UUID,
    query: CommentThreadQuery = Depends(),  # noqa: B008
    principal: Principal = Depends(optional_principal),  # noqa: B008
    comments: CommentService = Depends(get_comments),  # noqa: B008
) -> Page[CommentThread]:
    return await comments.list_threads(target_type, target_id, query=query, principal=principal)


@router.get(
    "/comments/moderation",
    response_model=Page[CommentRead],
    dependencies=[Depends(require_capability("comment:moderate"))],
    tags=["comment"],
)
async def list_comment_moderation(
    query: CommentModerationQuery = Depends(),  # noqa: B008
    comments: CommentService = Depends(get_comments),  # noqa: B008
) -> Page[CommentRead]:
    return await comments.list_moderation(query)


@router.post(
    "/comments", response_model=CommentRead, status_code=status.HTTP_201_CREATED, tags=["comment"]
)
async def create_comment(
    payload: CommentCreate,
    principal: Principal = Depends(require_authenticated),  # noqa: B008
    comments: CommentService = Depends(get_comments),  # noqa: B008
) -> CommentRead:
    return await comments.create(payload, principal)


@router.patch("/comments/{comment_id}", response_model=CommentRead, tags=["comment"])
async def update_comment(
    comment_id: UUID,
    payload: CommentUpdate,
    principal: Principal = Depends(require_authenticated),  # noqa: B008
    comments: CommentService = Depends(get_comments),  # noqa: B008
) -> CommentRead:
    return await comments.update(comment_id, payload, principal)


@router.get("/comments/{comment_id}", response_model=CommentRead, tags=["comment"])
async def get_comment(
    comment_id: UUID,
    principal: Principal = Depends(require_capability("comment:moderate")),  # noqa: B008
    comments: CommentService = Depends(get_comments),  # noqa: B008
) -> CommentRead:
    del principal
    return await comments.get(comment_id)


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["comment"])
async def delete_comment(
    comment_id: UUID,
    principal: Principal = Depends(require_authenticated),  # noqa: B008
    comments: CommentService = Depends(get_comments),  # noqa: B008
) -> None:
    await comments.delete(comment_id, principal)


@router.post("/comments/{comment_id}/moderate", response_model=CommentRead, tags=["comment"])
async def moderate_comment(
    comment_id: UUID,
    payload: ModerateRequest,
    principal: Principal = Depends(require_authenticated),  # noqa: B008
    comments: CommentService = Depends(get_comments),  # noqa: B008
) -> CommentRead:
    return await comments.moderate(comment_id, payload.action, principal)


@auth_router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    auth: AuthService = Depends(get_auth),  # noqa: B008
    settings: SettingsService = Depends(get_runtime_settings),  # noqa: B008
) -> UserRead:
    profile = await settings.get("site.profile")
    return await auth.register(
        payload,
        AuthRegistrationPolicy(
            registration_open=getattr(profile, "registration_open", True),
            default_role=getattr(profile, "default_registration_role", "reader"),
        ),
    )


@auth_router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
async def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    auth: AuthService = Depends(get_auth),  # noqa: B008
    mail: MailService = Depends(get_mail),  # noqa: B008
) -> None:
    delivery = await auth.request_password_reset(payload, ip=_request_ip(request))
    if delivery is not None:
        base_url = request.app.state.container.settings.public_base_url.rstrip("/")
        reset_url = f"{base_url}/account/reset-password?token={quote(delivery.token)}"
        await mail.enqueue(
            delivery.email,
            "auth.password_reset",
            PasswordResetMailContext(reset_url=reset_url, expires_minutes=30),
        )


@auth_router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    payload: ResetPasswordRequest,
    auth: AuthService = Depends(get_auth),  # noqa: B008
) -> None:
    await auth.reset_password(payload)


def _request_ip(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def _set_refresh_cookie(response: Response, request: Request, token: str) -> None:
    settings = request.app.state.container.settings
    response.set_cookie(
        settings.cookie_name,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/api/v1/auth",
        max_age=settings.jwt_refresh_ttl_seconds,
    )


@auth_router.post("/login", response_model=TokenPair)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    auth: AuthService = Depends(get_auth),  # noqa: B008
) -> TokenPair:
    pair = await auth.login(
        payload,
        ip=_request_ip(request),
        user_agent=request.headers.get("user-agent", ""),
    )
    _set_refresh_cookie(response, request, pair.refresh_token)
    return pair


@auth_router.post("/refresh", response_model=TokenPair)
async def refresh(
    request: Request,
    response: Response,
    payload: RefreshRequest | None = None,
    auth: AuthService = Depends(get_auth),  # noqa: B008
) -> TokenPair:
    token = request.cookies.get(request.app.state.container.settings.cookie_name)
    if not token and payload is not None:
        token = payload.refresh_token
    if not token:
        raise AppError(AUTH_003)
    pair = await auth.refresh(token)
    _set_refresh_cookie(response, request, pair.refresh_token)
    return pair


@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    payload: RefreshRequest | None = None,
    auth: AuthService = Depends(get_auth),  # noqa: B008
) -> None:
    token = request.cookies.get(request.app.state.container.settings.cookie_name)
    if not token and payload is not None:
        token = payload.refresh_token
    if token:
        await auth.logout(token)
    response.delete_cookie(request.app.state.container.settings.cookie_name, path="/api/v1/auth")


@auth_router.get("/me", response_model=AuthMe)
async def me(
    principal: Principal = Depends(require_authenticated),  # noqa: B008
    auth: AuthService = Depends(get_auth),  # noqa: B008
) -> AuthMe:
    return await auth.me(principal)


@router.put(
    "/interactions/content/{content_id}/like",
    response_model=InteractionRead,
    tags=["interaction"],
)
async def like_content(
    content_id: UUID,
    principal: Principal = Depends(require_authenticated),  # noqa: B008
    interactions: InteractionService = Depends(get_interactions),  # noqa: B008
) -> InteractionRead:
    return await interactions.like(content_id, principal)


@router.delete(
    "/interactions/content/{content_id}/like",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["interaction"],
)
async def unlike_content(
    content_id: UUID,
    principal: Principal = Depends(require_authenticated),  # noqa: B008
    interactions: InteractionService = Depends(get_interactions),  # noqa: B008
) -> None:
    await interactions.unlike(content_id, principal)


@router.put(
    "/interactions/content/{content_id}/rating",
    response_model=InteractionRead,
    tags=["interaction"],
)
async def rate_content(
    content_id: UUID,
    payload: RatingWrite,
    principal: Principal = Depends(require_authenticated),  # noqa: B008
    interactions: InteractionService = Depends(get_interactions),  # noqa: B008
) -> InteractionRead:
    return await interactions.rate(content_id, payload, principal)


@router.delete(
    "/interactions/content/{content_id}/rating",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["interaction"],
)
async def unrate_content(
    content_id: UUID,
    principal: Principal = Depends(require_authenticated),  # noqa: B008
    interactions: InteractionService = Depends(get_interactions),  # noqa: B008
) -> None:
    await interactions.unrate(content_id, principal)


@router.get("/me/interactions", response_model=Page[InteractionRead], tags=["interaction"])
async def interaction_history(
    query: InteractionQuery = Depends(),  # noqa: B008
    principal: Principal = Depends(require_authenticated),  # noqa: B008
    interactions: InteractionService = Depends(get_interactions),  # noqa: B008
) -> Page[InteractionRead]:
    return await interactions.history(query, principal)


@router.get("/audit-logs", dependencies=[Depends(require_capability("audit:read"))], tags=["audit"])
async def audit_logs(
    query: AuditQuery = Depends(),  # noqa: B008
    audit: AuditService = Depends(get_audit),  # noqa: B008
) -> Page[AuditLogRead]:
    return await audit.query(query)


@router.get(
    "/audit-logs/{log_id}",
    response_model=AuditLogRead,
    dependencies=[Depends(require_capability("audit:read"))],
    tags=["audit"],
)
async def get_audit_log(
    log_id: UUID,
    audit: AuditService = Depends(get_audit),  # noqa: B008
) -> AuditLogRead:
    return await audit.get(log_id)


@router.get(
    "/settings",
    response_model=list[SettingGroupRead],
    dependencies=[Depends(require_capability("setting:read"))],
    tags=["settings"],
)
async def list_settings(
    settings: SettingsService = Depends(get_runtime_settings),  # noqa: B008
) -> list[SettingGroupRead]:
    return await settings.list()


@public_router.get("/settings", response_model=PublicSettingsRead)
async def public_settings(
    settings: SettingsService = Depends(get_runtime_settings),  # noqa: B008
) -> PublicSettingsRead:
    return PublicSettingsRead(site_profile=await settings.public("site.profile"))


@router.patch(
    "/settings/{group_slug}",
    response_model=SettingGroupRead,
    dependencies=[Depends(require_capability("setting:update"))],
    tags=["settings"],
)
async def update_setting_group(
    group_slug: str,
    payload: SettingPatch,
    principal: Principal = Depends(require_authenticated),  # noqa: B008
    settings: SettingsService = Depends(get_runtime_settings),  # noqa: B008
) -> SettingGroupRead:
    return await settings.update(group_slug, payload, principal)


@router.get(
    "/tasks",
    response_model=Page[TaskInstanceRead],
    dependencies=[Depends(require_capability("task:manage"))],
    tags=["tasks"],
)
async def list_tasks(
    query: TaskQuery = Depends(),  # noqa: B008
    scheduler: TaskScheduler = Depends(get_scheduler),  # noqa: B008
) -> Page[TaskInstanceRead]:
    return await scheduler.list_instances(query)


@router.get(
    "/tasks/{task_id}",
    response_model=TaskInstanceRead,
    dependencies=[Depends(require_capability("task:manage"))],
    tags=["tasks"],
)
async def get_task(
    task_id: UUID,
    scheduler: TaskScheduler = Depends(get_scheduler),  # noqa: B008
) -> TaskInstanceRead:
    return await scheduler.get_instance(task_id)


@router.get(
    "/roles",
    response_model=list[RoleRead],
    dependencies=[Depends(require_capability("role:manage"))],
    tags=["rbac"],
)
async def list_roles(rbac: RBACService = Depends(get_rbac)) -> list[RoleRead]:  # noqa: B008
    return await rbac.list_roles()


@router.get(
    "/permissions",
    response_model=list[PermissionRead],
    dependencies=[Depends(require_capability("role:manage"))],
    tags=["rbac"],
)
async def list_permissions(
    rbac: RBACService = Depends(get_rbac),  # noqa: B008
) -> list[PermissionRead]:  # noqa: B008
    return await rbac.list_permissions()


@router.post(
    "/users/{user_id}/roles",
    response_model=UserRead,
    dependencies=[Depends(require_capability("role:assign"))],
    tags=["rbac"],
)
async def assign_user_role(
    user_id: UUID,
    payload: RoleAssign,
    principal: Principal = Depends(require_authenticated),  # noqa: B008
    rbac: RBACService = Depends(get_rbac),  # noqa: B008
) -> UserRead:
    return await rbac.assign_role(user_id, payload, actor=principal)


@router.put(
    "/users/{user_id}/roles",
    response_model=UserAdminRead,
    dependencies=[Depends(require_capability("role:assign"))],
    tags=["rbac"],
)
async def replace_user_roles(
    user_id: UUID,
    payload: UserRoleSet,
    principal: Principal = Depends(require_authenticated),  # noqa: B008
    rbac: RBACService = Depends(get_rbac),  # noqa: B008
) -> UserAdminRead:
    return await rbac.replace_roles(user_id, payload, actor=principal)


@router.get(
    "/users",
    response_model=Page[UserAdminRead],
    dependencies=[Depends(require_capability("user:read_any"))],
    tags=["users"],
)
async def list_users(
    query: UserQuery = Depends(),  # noqa: B008
    rbac: RBACService = Depends(get_rbac),  # noqa: B008
) -> Page[UserAdminRead]:
    return await rbac.list_users(query)


@router.get(
    "/users/{user_id}",
    response_model=UserAdminRead,
    dependencies=[Depends(require_capability("user:read_any"))],
    tags=["users"],
)
async def get_user(
    user_id: UUID,
    rbac: RBACService = Depends(get_rbac),  # noqa: B008
) -> UserAdminRead:
    return await rbac.get_user(user_id)


@router.patch(
    "/users/{user_id}",
    response_model=UserAdminRead,
    dependencies=[Depends(require_capability("user:update_any"))],
    tags=["users"],
)
async def update_user(
    user_id: UUID,
    payload: UserAdminUpdate,
    identity: IdentityService = Depends(get_identity),  # noqa: B008
    rbac: RBACService = Depends(get_rbac),  # noqa: B008
) -> UserAdminRead:
    await identity.update(user_id, payload)
    return await rbac.get_user(user_id)


@router.post(
    "/users/{user_id}/ban",
    response_model=UserRead,
    dependencies=[Depends(require_capability("user:ban"))],
    tags=["users"],
)
async def ban_user(
    user_id: UUID,
    principal: Principal = Depends(require_authenticated),  # noqa: B008
    identity: IdentityService = Depends(get_identity),  # noqa: B008
) -> UserRead:
    return await identity.ban(user_id, principal)


@router.post(
    "/users/{user_id}/unban",
    response_model=UserRead,
    dependencies=[Depends(require_capability("user:ban"))],
    tags=["users"],
)
async def unban_user(
    user_id: UUID,
    principal: Principal = Depends(require_authenticated),  # noqa: B008
    identity: IdentityService = Depends(get_identity),  # noqa: B008
) -> UserRead:
    return await identity.unban(user_id, principal)


router.include_router(auth_router)
router.include_router(public_router)
