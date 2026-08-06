"""Built-in runtime-setting declarations."""

from __future__ import annotations

import re
from typing import Any, Literal
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .definitions import SettingField, SettingGroup


def _validate_icon_url(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("icon_url must be an absolute HTTP(S) URL")
    return value


def _validate_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("timezone must be a valid IANA timezone") from exc
    return value


def _validate_title_format(value: str) -> str:
    allowed = {"{page_title}", "{site_title}"}
    tokens = set(re.findall(r"\{[^{}]+\}", value))
    if tokens - allowed:
        raise ValueError("title_format contains an unsupported placeholder")
    if "{site_title}" not in value:
        raise ValueError("title_format must contain {site_title}")
    return value


class SiteProfileSettings(SettingGroup):
    slug = "site.profile"
    group_title = "站点资料"
    group_description = "站点公开资料、注册策略和展示设置"
    order = 10

    title = SettingField(
        slug="title",
        title="站点标题",
        description="显示在页面标题中",
        value_type=str,
        default="aiya-cms",
        is_public=True,
    )
    subtitle = SettingField(
        slug="subtitle",
        title="站点副标题",
        description="显示在站点标题附近的副标题",
        value_type=str,
        default="",
        is_public=True,
    )
    description = SettingField(
        slug="description",
        title="站点描述",
        description="站点默认描述",
        value_type=str,
        default="",
        is_public=True,
    )
    icon_url = SettingField(
        slug="icon_url",
        title="图标地址",
        description="绝对 HTTP(S) 图标地址",
        value_type=str | None,
        default=None,
        is_public=True,
        validator=_validate_icon_url,
    )
    title_format = SettingField(
        slug="title_format",
        title="标题格式",
        description="必须包含 {site_title}，可选 {page_title}",
        value_type=str,
        default="{page_title} | {site_title}",
        is_public=True,
        validator=_validate_title_format,
    )
    admin_email = SettingField(
        slug="admin_email",
        title="管理员邮箱",
        description="仅管理员使用的站点联系邮箱",
        value_type=str | None,
        default=None,
    )
    registration_open = SettingField(
        slug="registration_open",
        title="开放注册",
        description="是否允许新用户注册",
        value_type=bool,
        default=True,
        is_public=True,
    )
    default_registration_role = SettingField(
        slug="default_registration_role",
        title="默认注册角色",
        description="新用户注册时分配的默认角色",
        value_type=Literal["reader", "member"],
        default="reader",
    )
    timezone = SettingField(
        slug="timezone",
        title="时区",
        description="站点使用的 IANA 时区",
        value_type=str,
        default="UTC",
        is_public=True,
        validator=_validate_timezone,
    )
    date_format = SettingField(
        slug="date_format",
        title="日期格式",
        description="站点日期显示格式",
        value_type=Literal["YYYY-MM-DD", "DD/MM/YYYY", "MM/DD/YYYY"],
        default="YYYY-MM-DD",
        is_public=True,
    )
    indexing_enabled = SettingField(
        slug="indexing_enabled",
        title="允许索引",
        description="是否允许站点内容被搜索引擎索引",
        value_type=bool,
        default=False,
        is_public=True,
    )


SiteProfile = SiteProfileSettings.value_model()


def public_site_profile(value: Any) -> dict[str, Any]:
    """Return the explicit public projection for the built-in profile group."""

    return {
        field.slug: getattr(value, field.slug)
        for field in SiteProfileSettings.fields()
        if field.is_public
    }
