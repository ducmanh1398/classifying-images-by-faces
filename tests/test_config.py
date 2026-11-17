import dataclasses

import pytest

from facesort.config import Config, load_config, save_config
from facesort.errors import ConfigError


def make(tmp_path, **kw):
    return Config(input_dir=str(tmp_path / "in"), output_dir=str(tmp_path / "out"), **kw)


def test_roundtrip_with_vietnamese_path(tmp_path):
    cfg = Config(input_dir=str(tmp_path / "Ảnh cưới"), output_dir=str(tmp_path / "Đầu ra"))
    p = tmp_path / "config.toml"
    save_config(cfg, p)
    assert load_config(p) == cfg


def test_defaults_valid(tmp_path):
    make(tmp_path).validate()


@pytest.mark.parametrize(
    "kw",
    [
        {"det_size": 100},
        {"det_size": 0},
        {"min_det_score": 1.5},
        {"min_face_px": 0},
        {"min_face_ratio": -0.1},
        {"cluster_eps": 0},
        {"cluster_eps": 3},
        {"cluster_min_samples": 0},
        {"assign_threshold": 0},
        {"extensions": ()},
        {"unlabeled_folder": "a/b"},
        {"unlabeled_folder": " "},
    ],
)
def test_invalid(tmp_path, kw):
    with pytest.raises(ConfigError):
        make(tmp_path, **kw).validate()


def test_output_inside_input(tmp_path):
    cfg = Config(input_dir=str(tmp_path / "in"), output_dir=str(tmp_path / "in" / "out"))
    with pytest.raises(ConfigError):
        cfg.validate()


def test_input_inside_output(tmp_path):
    cfg = Config(input_dir=str(tmp_path / "out" / "in"), output_dir=str(tmp_path / "out"))
    with pytest.raises(ConfigError):
        cfg.validate()


def test_same_dir(tmp_path):
    cfg = Config(input_dir=str(tmp_path), output_dir=str(tmp_path))
    with pytest.raises(ConfigError):
        cfg.validate()


def test_unknown_key(tmp_path):
    p = tmp_path / "config.toml"
    save_config(make(tmp_path), p)
    p.write_text(p.read_text(encoding="utf-8") + "bogus = 1\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(p)


def test_all_keys_written(tmp_path):
    p = tmp_path / "config.toml"
    save_config(make(tmp_path), p)
    text = p.read_text(encoding="utf-8")
    for f in dataclasses.fields(Config):
        assert f.name in text
