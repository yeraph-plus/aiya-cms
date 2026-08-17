"""Production membership grant declaration contract."""

from inc.features.membership_grants.definition import behavior_specs, spec


def test_membership_grants_is_payment_independent() -> None:
    assert spec.name == "membership_grants"
    assert spec.requires == ("membership", "points")
    assert len(behavior_specs) == 1
    behavior = behavior_specs[0]
    assert behavior.key == "membership.grant"
    assert behavior.program_key == "credit"
    assert behavior.direction == "credit"
    assert behavior.allowed_source_types == ("membership",)
