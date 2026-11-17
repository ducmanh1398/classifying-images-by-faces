"""Bản giả của bộ nhận diện (và sau này của Drive)."""

from __future__ import annotations

import numpy as np

from facesort.detect import Detection


def unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32)
    return v / np.linalg.norm(v)


def det(x=10, y=10, size=100, score=0.9, emb=None) -> Detection:
    if emb is None:
        emb = unit(np.random.default_rng(0).normal(size=512))
    return Detection(x, y, size, size, score, np.asarray(emb, dtype=np.float32))


class FakeFaceEngine:
    """Trả kết quả định sẵn theo thứ tự gọi; phần tử là list[Detection] hoặc Exception."""

    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def detect(self, image):
        r = self.results[self.calls]
        self.calls += 1
        if isinstance(r, BaseException):
            raise r
        return r
