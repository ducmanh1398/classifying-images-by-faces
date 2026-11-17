"""Đọc, ghi và kiểm tra config.toml (đặc tả mục 4)."""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

from .errors import ConfigError


@dataclass
class Config:
    input_dir: str
    output_dir: str
    extensions: tuple[str, ...] = ("jpg", "jpeg", "png", "heic", "heif")
    det_size: int = 960
    min_det_score: float = 0.5
    min_face_px: int = 60
    min_face_ratio: float = 0.25
    cluster_eps: float = 0.5
    cluster_min_samples: int = 3
    assign_threshold: float = 0.45
    export_unlabeled: bool = True
    unlabeled_folder: str = "_Khac"

    def validate(self) -> None:
        if not self.input_dir or not self.output_dir:
            raise ConfigError("Thiếu input_dir hoặc output_dir.")
        inp = Path(self.input_dir).resolve()
        out = Path(self.output_dir).resolve()
        if inp == out or out.is_relative_to(inp):
            raise ConfigError("output_dir không được nằm trong input_dir.")
        if inp.is_relative_to(out):
            raise ConfigError("input_dir không được nằm trong output_dir.")
        if not self.extensions:
            raise ConfigError("extensions không được rỗng.")
        if self.det_size <= 0 or self.det_size % 32:
            raise ConfigError("det_size phải là bội số của 32.")
        if not 0 <= self.min_det_score <= 1:
            raise ConfigError("min_det_score phải trong khoảng 0 đến 1.")
        if self.min_face_px < 1:
            raise ConfigError("min_face_px phải từ 1 trở lên.")
        if not 0 <= self.min_face_ratio <= 1:
            raise ConfigError("min_face_ratio phải trong khoảng 0 đến 1.")
        if not 0 < self.cluster_eps <= 2:
            raise ConfigError("cluster_eps phải trong khoảng (0, 2].")
        if self.cluster_min_samples < 1:
            raise ConfigError("cluster_min_samples phải từ 1 trở lên.")
        if not 0 < self.assign_threshold <= 2:
            raise ConfigError("assign_threshold phải trong khoảng (0, 2].")
        name = self.unlabeled_folder.strip()
        if not name or any(c in name for c in '<>:"/\\|?*'):
            raise ConfigError("unlabeled_folder không hợp lệ.")

    @property
    def ext_set(self) -> frozenset[str]:
        return frozenset(e.lower().lstrip(".") for e in self.extensions)


def _toml_value(v: object) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    raise TypeError(type(v))


def dumps(config: Config) -> str:
    return "".join(f"{f.name} = {_toml_value(getattr(config, f.name))}\n" for f in fields(Config))


def save_config(config: Config, path: Path) -> None:
    path.write_text(dumps(config), encoding="utf-8")


def load_config(path: Path) -> Config:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise ConfigError(f"Không đọc được {path}: {e}") from e
    known = {f.name for f in fields(Config)}
    unknown = set(data) - known
    if unknown:
        raise ConfigError(f"Khóa không hợp lệ trong config.toml: {', '.join(sorted(unknown))}")
    if "extensions" in data:
        data["extensions"] = tuple(data["extensions"])
    try:
        cfg = Config(**data)
    except TypeError as e:
        raise ConfigError(f"config.toml thiếu khóa bắt buộc: {e}") from e
    cfg.validate()
    return cfg
