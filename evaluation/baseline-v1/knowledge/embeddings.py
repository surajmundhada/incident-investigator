import hashlib
import json
import math
import threading
from importlib.metadata import version
from pathlib import Path


def validate_vectors(vectors, expected_count):
    if len(vectors) != expected_count:
        raise ValueError("Embedding count does not match passage count")
    for row in vectors:
        if len(row) != 384 or not all(math.isfinite(x) for x in row):
            raise ValueError("Expected finite 384-dimensional embeddings")
        if sum(x * x for x in row) < 1e-12:
            raise ValueError("Zero embeddings cannot be used for cosine retrieval")
    return vectors


class LocalEmbedder:
    def __init__(self, directory, lock_path=None):
        root = Path(__file__).resolve().parents[3]
        lock_path = Path(lock_path or root / "knowledge" / "embedding-lock.json")
        spec = json.loads(lock_path.read_text(encoding="utf-8"))
        directory = Path(directory)
        if version("fastembed") != spec["fastembed_version"]:
            raise ValueError("Embedding runtime differs from the locked version")
        for name, checksum in spec["files"].items():
            path = directory / name
            if not checksum or hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
                raise ValueError(f"Missing or mismatched local model artifact: {name}")
        from fastembed import TextEmbedding
        from tokenizers import Tokenizer

        self.identity = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
        self.lock = threading.RLock()
        self.spec = spec
        self.tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()
        self.model = TextEmbedding(
            model_name=spec["model"],
            specific_model_path=str(directory),
            local_files_only=True,
            threads=2,
            providers=["CPUExecutionProvider"],
        )

    def token_count(self, text):
        with self.lock:
            return len(self.tokenizer.encode(text).ids)

    def embed(self, texts):
        with self.lock:
            if any(self.token_count(text) > 256 for text in texts):
                raise ValueError("Input exceeds the embedding model's token limit")
            vectors = [row.tolist() for row in self.model.embed(texts, batch_size=16)]
            return validate_vectors(vectors, len(texts))
