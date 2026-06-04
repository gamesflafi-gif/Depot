"""Embeddings – lokal & kostenlos (kein API).

Zwei Implementierungen mit gleicher Schnittstelle:
- ``FastEmbedEmbedder``: echte semantische Embeddings über ``fastembed`` (ONNX,
  CPU-freundlich, kein PyTorch). Modell wird einmal heruntergeladen, läuft dann
  offline auf dem Server.
- ``HashEmbedder``: deterministische, abhängigkeitsfreie Hash-Embeddings als
  **Offline-Fallback** (für Tests/Demo ohne Modell-Download). Liefert sinnvolle
  Ähnlichkeit über Wortüberlappung.

So laufen Tests ohne Netzwerk, und auf dem Server bekommst du echte Semantik.
"""
from __future__ import annotations

import hashlib
import logging
import re

import numpy as np

log = logging.getLogger(__name__)
_TOKEN = re.compile(r"[A-Za-zÄÖÜäöüß0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN.findall((text or "").lower())


class HashEmbedder:
    """Deterministische Hash-Embeddings (Bag-of-Words, L2-normiert)."""
    name = "hash"

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def embed(self, texts: list[str]) -> np.ndarray:
        vecs = np.zeros((len(texts), self.dim), dtype="float32")
        for i, t in enumerate(texts):
            for tok in _tokenize(t):
                h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
                vecs[i, h % self.dim] += 1.0
            n = np.linalg.norm(vecs[i])
            if n > 0:
                vecs[i] /= n
        return vecs


class FastEmbedEmbedder:
    """Echte semantische Embeddings via fastembed (ONNX, CPU)."""
    name = "fastembed"

    def __init__(self, model: str = "BAAI/bge-small-en-v1.5") -> None:
        from fastembed import TextEmbedding
        self.model_name = model
        self._m = TextEmbedding(model_name=model)
        self.dim = 384  # bge-small

    def embed(self, texts: list[str]) -> np.ndarray:
        return np.asarray(list(self._m.embed(texts)), dtype="float32")


def get_embedder(prefer: str = "auto", dim: int = 256):
    """Wählt den Embedder. ``auto`` nimmt fastembed, fällt auf Hash zurück."""
    if prefer in ("fastembed", "auto"):
        try:
            return FastEmbedEmbedder()
        except Exception as exc:  # noqa: BLE001
            if prefer == "fastembed":
                raise
            log.warning("fastembed nicht verfügbar (%s) – nutze Hash-Embedder.", exc)
    return HashEmbedder(dim=dim)
