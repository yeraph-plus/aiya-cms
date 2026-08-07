"""Site settings feature: declarative settings groups in one place.

Contract source: context/spec/features.md §4.5.

The site_settings feature declares the site-level settings groups
(general, seo, notification). settings stays a passive host; the
composition root registers the returned specs explicitly and freezes the
registry.
"""

from inc.features.site_settings.definition import build_site_setting_group_specs

__all__ = ["build_site_setting_group_specs"]
