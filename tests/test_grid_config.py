from pathlib import Path

from skill_taint.grid import (
    ROOT,
    committed_specs,
    extension_specs,
    formal_record_specs,
    load_grid,
    load_record_grid,
    record_specs,
)


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
    record = load_record_grid(path=ROOT / "configs" / "record_update.yaml")
    specs = record_specs(grid=record)
    assert len(specs) == 27
    assert len({spec.campaign_id for spec in specs}) == 27
    assert {spec.phrasing for spec in specs} == {"plain"}
    assert {spec.condition for spec in specs} == {"off", "spotlight", "quarantine"}
    assert {spec.family for spec in specs} == {"record_update"}
    formal = formal_record_specs(grid=record)
    assert len(formal) == 18
    assert {spec.condition for spec in formal} == {"off", "quarantine"}
    assert {spec.phrasing for spec in formal} == {"formal"}
