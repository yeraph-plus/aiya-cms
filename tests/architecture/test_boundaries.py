"""M0 architecture guard skeleton; rules expand with each kernel/module milestone."""

from pathlib import Path


def test_expected_layer_roots_exist() -> None:
    source_root = Path(__file__).parents[2] / "inc"

    assert (source_root / "kernel").is_dir()
    assert (source_root / "modules").is_dir()
    assert (source_root / "api").is_dir()
