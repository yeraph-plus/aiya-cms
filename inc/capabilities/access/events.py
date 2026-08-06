"""Access events.

Contract source: context/spec/capabilities/access.md §7.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RoleChangedPayload(_Payload):
    role_id: str
    action: str  # created | updated | deleted | capabilities_replaced


class SubjectRoleAssignedPayload(_Payload):
    subject_type: str
    subject_id: str
    role_id: str
    scope: str = "global"


class SubjectRoleRevokedPayload(_Payload):
    subject_type: str
    subject_id: str
    role_id: str


ACCESS_EVENT_SCHEMAS: dict[str, type[BaseModel]] = {
    "access.role_changed.v1": RoleChangedPayload,
    "access.subject_role_assigned.v1": SubjectRoleAssignedPayload,
    "access.subject_role_revoked.v1": SubjectRoleRevokedPayload,
}
