from pathlib import Path

import pytest

from skill_integrity.cli import main
from skill_integrity.errors import ConfigError, MissingConfigError
from skill_integrity.evaluate import run_mock_compare


def test_readme_records_the_mock_report(tmp_path: Path) -> None:
    report = run_mock_compare(workdir=tmp_path)
    readme = Path(__file__).resolve().parents[1].joinpath("README.md").read_text(encoding="utf-8")
    assert report in readme


def test_compare_prints_the_mock_table(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(argv=["--backend", "mock", "--defense", "compare", "--workdir", str(tmp_path)])
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "real_llm_results: not run" in captured.out
    assert "| off | 3/3 | 0/3 | 1/1 | 0/1 | 1/1 | 0 | 0 |" in captured.out
    assert "| segment | 0/3 | 3/3 | 1/1 | 1/1 | 1/1 | 0 | 0 |" in captured.out
    assert (tmp_path / "report.txt").read_text(encoding="utf-8") == captured.out


def test_openai_without_a_key_raises_and_does_not_create_a_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    with pytest.raises(MissingConfigError) as caught:
        main(
            argv=[
                "--backend",
                "openai",
                "--defense",
                "segment",
                "--model",
                "test-model",
                "--base-url",
                "https://example.invalid/v1",
                "--workdir",
                str(tmp_path),
            ]
        )
    assert "OPENAI_API_KEY" in caught.value.missing
    assert list(tmp_path.iterdir()) == []


def test_empty_api_key_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    with pytest.raises(MissingConfigError):
        main(
            argv=[
                "--backend",
                "openai",
                "--defense",
                "segment",
                "--workdir",
                str(tmp_path),
            ]
        )


def test_mock_rejects_openai_flags_and_a_nonempty_workdir(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        main(
            argv=[
                "--backend",
                "mock",
                "--defense",
                "off",
                "--model",
                "test-model",
                "--workdir",
                str(tmp_path),
            ]
        )
    with pytest.raises(ConfigError):
        main(
            argv=[
                "--backend",
                "mock",
                "--defense",
                "compare",
                "--endorse",
                "--workdir",
                str(tmp_path),
            ]
        )
    (tmp_path / "existing.txt").write_text(data="x", encoding="utf-8")
    with pytest.raises(ConfigError):
        main(
            argv=[
                "--backend",
                "mock",
                "--defense",
                "compare",
                "--workdir",
                str(tmp_path),
            ]
        )
