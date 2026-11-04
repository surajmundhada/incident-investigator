"""Application-scoped batch embedding cache; local inference remains the fallback."""

import hashlib
import json
import math

from .cache import CACHE_FORMAT, EMBEDDING_TTL
from .embeddings import validate_vectors


class CachedEmbeddings:
    def __init__(self, embedder, cache):
        self.embedder, self.cache = embedder, cache

    def embed(self, texts, application):
        # Preserve the tokenizer boundary on every call, including fully cached batches.
        if any(self.embedder.token_count(value) > 256 for value in texts):
            raise ValueError("Input exceeds the embedding model's token limit")
        unique = list(dict.fromkeys(texts))
        scopes = [
            {
                "format": CACHE_FORMAT,
                "application": application,
                "embedding": self.embedder.identity,
                "text_hash": hashlib.sha256(value.encode()).hexdigest(),
            }
            for value in unique
        ]
        keys = [self.cache.key("embedding", scope) for scope in scopes]
        values, missing = {}, []
        for value, scope, raw in zip(unique, scopes, self.cache.read_many(keys), strict=True):
            entry = self.cache.decode(raw)
            try:
                if (
                    not isinstance(entry, dict)
                    or set(entry) != {"scope", "vector"}
                    or entry["scope"] != scope
                ):
                    raise ValueError()
                vector = entry["vector"]
                if not isinstance(vector, list) or any(
                    type(x) not in {int, float} or abs(x) > 3.4e38 for x in vector
                ):
                    raise ValueError()
                validate_vectors([vector], 1)
                if not math.isfinite(sum(x * x for x in vector)):
                    raise ValueError()
                values[value] = vector
                self.cache.metrics.add("embedding_hits")
            except (ValueError, TypeError, OverflowError, KeyError):
                if raw is not None and entry is not None:
                    self.cache.metrics.add("corrupt")
                missing.append(value)
                self.cache.metrics.add("embedding_misses")
        if missing:
            self.cache.metrics.add("encoder_inputs", len(missing))
            vectors = validate_vectors(self.embedder.embed(missing), len(missing))
            values.update(zip(missing, vectors, strict=True))
            pending = {
                key: json.dumps(
                    {"scope": scope, "vector": values[value]},
                    allow_nan=False,
                    separators=(",", ":"),
                ).encode()
                for key, scope, value in zip(keys, scopes, unique, strict=True)
                if value in missing
            }
            self.cache.write_many(pending, EMBEDDING_TTL)
        self.cache.metrics.add("encoder_inputs_avoided", len(texts) - len(missing))
        return [list(values[value]) for value in texts]
