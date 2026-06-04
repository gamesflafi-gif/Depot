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

    def embed(self, texts: list[str], kind: str = "passage") -> np.ndarray:
        vecs = np.zeros((len(texts), self.dim), dtype="float32")
        for i, t in enumerate(texts):
            for tok in _tokenize(t):
                h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
                vecs[i, h % self.dim] += 1.0
            n = np.linalg.norm(vecs[i])
            if n > 0:
                vecs[i] /= n
        return vecs


# Bevorzugt mehrsprachig (versteht u.a. Deutsch), Fallback englisch.
_MODELS = ["intfloat/multilingual-e5-small", "BAAI/bge-small-en-v1.5"]


class FastEmbedEmbedder:
    """Echte semantische Embeddings via fastembed (ONNX, CPU). Mehrsprachig."""
    name = "fastembed"

    def __init__(self, model: str | None = None) -> None:
        from fastembed import TextEmbedding
        last = None
        for m in ([model] if model else _MODELS):
            try:
                self._m = TextEmbedding(model_name=m)
                self.model_name = m
                break
            except Exception as exc:  # noqa: BLE001
                last = exc
        else:
            raise RuntimeError(f"Kein Embedding-Modell ladbar: {last}")
        self.dim = 384
        self._e5 = "e5" in self.model_name.lower()

    def embed(self, texts: list[str], kind: str = "passage") -> np.ndarray:
        # e5-Modelle brauchen Präfixe "query:"/"passage:" für beste Qualität.
        if self._e5:
            pre = "query: " if kind == "query" else "passage: "
            texts = [pre + t for t in texts]
        # parallel=1: KEIN Multiprocessing -> nur EINE Modellkopie (spart RAM!)
        return np.asarray(list(self._m.embed(texts, batch_size=64, parallel=1)),
                          dtype="float32")


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
