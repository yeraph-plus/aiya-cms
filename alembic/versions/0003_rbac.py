"""Create RBAC tables and canonical role/permission seed."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from inc.kernel.db import new_uuid7

revision: str = "0003_rbac"
down_revision: str | None = "0002_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CAPABILITIES = (
    ("user:read_any", "管理端读取任意用户"),
    ("user:update_any", "管理端修改任意用户"),
    ("user:ban", "封禁或解封用户"),
    ("role:manage", "角色与权限点管理"),
    ("role:assign", "给用户授予角色"),
    ("audit:read", "读取审计日志"),
    ("setting:read", "读取设置"),
    ("setting:update", "修改设置"),
    ("task:manage", "查看或干预任务实例"),
    ("content:create", "创建内容"),
    ("content:update_own", "修改自己的内容"),
    ("content:update_any", "修改任意内容"),
    ("content:delete_own", "删除自己的内容"),
    ("content:delete_any", "删除任意内容"),
    ("content:publish", "发布或下架内容"),
    ("term:manage", "管理 term"),
    ("term:assign", "给内容关联 term"),
    ("comment:create", "发表评论"),
    ("comment:update_own", "修改自己的评论"),
    ("comment:delete_own", "删除自己的评论"),
    ("comment:delete_any", "删除任意评论"),
    ("comment:moderate", "审核评论"),
)

_ROLE_CAPABILITIES = {
    "moderator": (
        "comment:moderate",
        "comment:delete_any",
        "content:update_any",
        "content:delete_any",
    ),
    "editor": (
        "content:create",
        "content:update_own",
        "content:delete_own",
        "content:publish",
        "term:manage",
        "term:assign",
    ),
    "member": (
        "content:create",
        "content:update_own",
        "content:delete_own",
        "term:assign",
        "comment:create",
        "comment:update_own",
        "comment:delete_own",
    ),
    "reader": ("comment:create", "comment:update_own", "comment:delete_own"),
}


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(32), nullable=False),
        sa.Column("description", sa.String(256), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("name", name="roles_name_key"),
    )
    op.create_table(
        "permissions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("alias", sa.String(64), nullable=False),
        sa.Column("description", sa.String(256), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("alias", name="permissions_alias_key"),
    )
    op.create_table(
        "role_permissions",
        sa.Column(
            "role_id", sa.Uuid(), sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column(
            "permission_id",
            sa.Uuid(),
            sa.ForeignKey("permissions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_table(
        "user_roles",
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column(
            "role_id", sa.Uuid(), sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
    )

    permissions = {alias: new_uuid7() for alias, _ in _CAPABILITIES}
    op.bulk_insert(
        sa.table(
            "permissions",
            sa.column("id", sa.Uuid()),
            sa.column("alias", sa.String()),
            sa.column("description", sa.String()),
        ),
        [
            {"id": permission_id, "alias": alias, "description": description}
            for (alias, description), permission_id in zip(
                _CAPABILITIES, permissions.values(), strict=True
            )
        ],
    )

    role_ids = {name: new_uuid7() for name in ("admin", "moderator", "editor", "member", "reader")}
    op.bulk_insert(
        sa.table(
            "roles",
            sa.column("id", sa.Uuid()),
            sa.column("name", sa.String()),
            sa.column("description", sa.String()),
        ),
        [{"id": role_id, "name": name, "description": name} for name, role_id in role_ids.items()],
    )
    links = []
    for role_name, aliases in _ROLE_CAPABILITIES.items():
        links.extend(
            {"role_id": role_ids[role_name], "permission_id": permissions[alias]}
            for alias in aliases
        )
    links.extend(
        {"role_id": role_ids["admin"], "permission_id": permission_id}
        for permission_id in permissions.values()
    )
    op.bulk_insert(
        sa.table(
            "role_permissions",
            sa.column("role_id", sa.Uuid()),
            sa.column("permission_id", sa.Uuid()),
        ),
        links,
    )


def downgrade() -> None:
    op.drop_table("user_roles")
    op.drop_table("role_permissions")
    op.drop_table("permissions")
    op.drop_table("roles")
