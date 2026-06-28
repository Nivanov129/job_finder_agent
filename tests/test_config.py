"""Тесты загрузчика конфига."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from job_agent.config import Config, ConfigError, load_config

_REPO_ROOT = Path(__file__).resolve().parents[1]
_EXAMPLE = _REPO_ROOT / "config.example.json"


def test_example_config_loads() -> None:
    config = load_config(_EXAMPLE)
    assert isinstance(config, Config)
    assert config.version == 1
    assert len(config.tracks) == 2
    assert config.tracks[0].id == "scaleup"
    assert config.scoring_engine == "cli"
    assert config.is_single_track is False


def test_single_track_config(tmp_path: Path) -> None:
    data = {
        "version": 1,
        "tracks": [
            {"id": "backend", "name": "Backend", "resume_path": "./r.pdf"}
        ],
        "scoring_engine": "cli",
        "output_mode": "table",
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    config = load_config(path)
    assert config.is_single_track is True
    assert config.tracks[0].name == "Backend"
    # Дефолты из pydantic-модели
    assert config.use_aggregators is True
    assert config.cover_letter_threshold == 70


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="не найден"):
        load_config(tmp_path / "nope.json")


def test_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ConfigError, match="валидным JSON"):
        load_config(path)


def test_missing_required_field_gives_clear_error(tmp_path: Path) -> None:
    # Нет обязательного tracks.
    data = {"version": 1, "scoring_engine": "cli", "output_mode": "table"}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ConfigError, match="tracks"):
        load_config(path)


def test_empty_tracks_rejected(tmp_path: Path) -> None:
    data = {
        "version": 1,
        "tracks": [],
        "scoring_engine": "cli",
        "output_mode": "table",
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ConfigError, match="tracks"):
        load_config(path)


def test_bad_enum_points_to_field(tmp_path: Path) -> None:
    data = {
        "version": 1,
        "tracks": [{"id": "t", "name": "T", "resume_path": "./r.pdf"}],
        "scoring_engine": "gpt5",  # не из enum
        "output_mode": "table",
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ConfigError, match="scoring_engine"):
        load_config(path)


def test_unknown_property_rejected(tmp_path: Path) -> None:
    data = {
        "version": 1,
        "tracks": [{"id": "t", "name": "T", "resume_path": "./r.pdf"}],
        "scoring_engine": "cli",
        "output_mode": "table",
        "surprise": True,
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)
