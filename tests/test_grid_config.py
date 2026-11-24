from pathlib import Path

from skill_taint.grid import ROOT, committed_specs, extension_specs, load_grid


def test_committed_grid_has_36_campaigns_and_prices_match_the_catalog() -> None:
    grid = load_grid(path=ROOT / "configs" / "grid.yaml")
    specs = committed_specs(grid=grid, drop_spotlight=False)
    assert len(specs) == 36
    assert len({spec.campaign_id for spec in specs}) == 36
    dropped = committed_specs(grid=grid, drop_spotlight=True)
    assert len(dropped) == 27
    assert all(spec.condition != "spotlight" for spec in dropped)
    assert len(extension_specs(grid=grid)) == 18
    assert Path(ROOT / "configs" / "grid.yaml").is_file()
