import hashlib
import json
import math
import threading
from importlib.metadata import version
from pathlib import Path


class LocalReranker:
    def __init__(self, directory, lock_path=None):
        lock_path = Path(
            lock_path or Path(__file__).resolve().parents[3] / "knowledge/reranker-lock.json"
        )
        spec = json.loads(lock_path.read_text(encoding="utf-8"))
        directory = Path(directory)
        if version("fastembed") != spec["fastembed_version"]:
            raise ValueError("Reranker runtime differs from its lock")
        for name, checksum in spec["files"].items():
            if (
                not checksum
                or hashlib.sha256((directory / name).read_bytes()).hexdigest() != checksum
            ):
                raise ValueError("Missing or mismatched reranker artifact: " + name)
        from fastembed.rerank.cross_encoder import TextCrossEncoder
        from tokenizers import Tokenizer

        self.identity = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
        self.lock = threading.Lock()
        self.tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()
        self.model = TextCrossEncoder(
            model_name=spec["model"],
            specific_model_path=str(directory),
            local_files_only=True,
            threads=2,
            providers=["CPUExecutionProvider"],
        )

    def score(self, query, passages):
        texts = [row["title"] + "\n" + row["heading"] + "\n" + row["body"] for row in passages]
        with self.lock:
            if any(len(self.tokenizer.encode(query, text).ids) > 512 for text in texts):
                raise ValueError("Reranker pair exceeds its input limit")
            scores = list(self.model.rerank(query, texts, batch_size=8))
        if len(scores) != len(passages) or not all(math.isfinite(score) for score in scores):
            raise ValueError("Invalid reranker output")
        return scores
