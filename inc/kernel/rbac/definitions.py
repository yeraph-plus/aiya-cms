"""The canonical Capability and default-role registration table."""

from dataclasses import dataclass

from .registry import CapabilityDefinition
from .schemas import PolicyContext


def _owner_policy(principal, context: PolicyContext | None) -> bool:  # type: ignore[no-untyped-def]
    return context is not None and context.resource_owner_id == principal.id


def _publish_policy(principal, context: PolicyContext | None) -> bool:  # type: ignore[no-untyped-def]
    return _owner_policy(principal, context) or "content:update_any" in principal.capabilities


CORE_CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    CapabilityDefinition("user:read_any", "管理端读取任意用户"),
    CapabilityDefinition("user:update_any", "管理端修改任意用户", audited=True),
    CapabilityDefinition("user:ban", "封禁或解封用户", audited=True),
    CapabilityDefinition("role:manage", "角色与权限点管理", audited=True),
    CapabilityDefinition("role:assign", "给用户授予角色", audited=True),
    CapabilityDefinition("audit:read", "读取审计日志"),
    CapabilityDefinition("setting:read", "读取设置"),
    CapabilityDefinition("setting:update", "修改设置", audited=True),
    CapabilityDefinition("task:manage", "查看或干预任务实例"),
)

MODULE_CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    CapabilityDefinition("content:create", "创建内容"),
    CapabilityDefinition("content:update_own", "修改自己的内容", policy=_owner_policy),
    CapabilityDefinition("content:update_any", "修改任意内容", audited=True),
    CapabilityDefinition("content:delete_own", "删除自己的内容", policy=_owner_policy),
    CapabilityDefinition("content:delete_any", "删除任意内容", audited=True),
    CapabilityDefinition("content:publish", "发布或下架内容", policy=_publish_policy),
    CapabilityDefinition("term:manage", "管理 term"),
    CapabilityDefinition("term:assign", "给内容关联 term"),
    CapabilityDefinition("comment:create", "发表评论"),
    CapabilityDefinition("comment:update_own", "修改自己的评论", policy=_owner_policy),
    CapabilityDefinition("comment:delete_own", "删除自己的评论", policy=_owner_policy),
    CapabilityDefinition("comment:delete_any", "删除任意评论", audited=True),
    CapabilityDefinition("comment:moderate", "审核评论", audited=True),
)

ALL_CAPABILITIES = CORE_CAPABILITIES + MODULE_CAPABILITIES
ALL_CAPABILITY_ALIASES: tuple[str, ...] = tuple(item.alias for item in ALL_CAPABILITIES)


@dataclass(frozen=True, slots=True)
class RoleSeed:
    name: str
    description: str
    aliases: tuple[str, ...]


ROLE_SEEDS: tuple[RoleSeed, ...] = (
    RoleSeed("admin", "系统管理员", ALL_CAPABILITY_ALIASES),
    RoleSeed(
        "moderator",
        "评论与内容审核员",
        ("comment:moderate", "comment:delete_any", "content:update_any", "content:delete_any"),
    ),
    RoleSeed(
        "editor",
        "内容编辑",
        (
            "content:create",
            "content:update_own",
            "content:delete_own",
            "content:publish",
            "term:manage",
            "term:assign",
        ),
    ),
    RoleSeed(
        "member",
        "普通成员",
        (
            "content:create",
            "content:update_own",
            "content:delete_own",
            "term:assign",
            "comment:create",
            "comment:update_own",
            "comment:delete_own",
        ),
    ),
    RoleSeed("reader", "注册用户", ("comment:create", "comment:update_own", "comment:delete_own")),
)
