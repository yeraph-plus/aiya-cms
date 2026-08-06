"""G7 architecture tests for the API composition-root kernel cutover."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]


def test_api_routes_and_wiring_use_kernel_cms_services() -> None:
    routes = (REPO_ROOT / "inc" / "api" / "routes.py").read_text(encoding="utf-8")
    wiring = (REPO_ROOT / "inc" / "api" / "wiring.py").read_text(encoding="utf-8")
    for source in (routes, wiring):
        assert "inc.modules.content" not in source
        assert "inc.modules.taxonomy" not in source
        assert "inc.modules.comment" not in source
    assert "inc.kernel.content" in routes or "inc.kernel.content" in wiring
    assert "inc.kernel.taxonomy" in routes or "inc.kernel.taxonomy" in wiring
    assert "inc.kernel.comment" in routes or "inc.kernel.comment" in wiring


def test_api_wiring_connects_content_comment_count_recount() -> None:
    wiring = (REPO_ROOT / "inc" / "api" / "wiring.py").read_text(encoding="utf-8")
    assert "set_comment_stats" in wiring
    assert "content.recount_comments" in wiring
