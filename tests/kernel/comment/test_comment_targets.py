"""Comment target policy projection contracts."""

from __future__ import annotations

import pytest

from inc.kernel.comment.targets import CommentTargetPolicy


def test_comment_target_policy_validates_limits() -> None:
    policy = CommentTargetPolicy(max_depth=2, auto_approve=False, rate_limit=5)
    assert policy.max_depth == 2
    assert policy.auto_approve is False

    with pytest.raises(ValueError):
        CommentTargetPolicy(max_depth=-1)
    with pytest.raises(ValueError):
        CommentTargetPolicy(rate_limit=0)
