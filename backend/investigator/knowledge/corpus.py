import hashlib
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from investigator.catalog import DEFAULT_APPLICATION, Identifier

CHUNKER_VERSION = "heading-preserve-markdown-180-overlap12-v2"


class Document(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,79}$")
    path: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=3, max_length=120)
    service: Identifier
    application: Identifier = DEFAULT_APPLICATION
    environment: Literal["local", "staging", "production"] = "local"
    release: str = Field(default="demo-v1", pattern=r"^[a-zA-Z0-9_.-]{1,40}$")


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    documents: list[Document] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def unique_documents(self):
        if len({doc.application for doc in self.documents}) != 1:
            raise ValueError("A corpus must belong to exactly one application")
        for field in ("id", "path"):
            if len({getattr(doc, field) for doc in self.documents}) != len(self.documents):
                raise ValueError("Document IDs and paths must be unique")
        return self


def load_corpus(root):
    root = Path(root).resolve()
    manifest_path = root / "manifest.json"
    if manifest_path.stat().st_size > 32_000:
        raise ValueError("Manifest exceeds size limit")
    manifest = Manifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    documents = []
    total = 0
    for metadata in sorted(manifest.documents, key=lambda doc: doc.id):
        path = (root / metadata.path).resolve()
        if not path.is_relative_to(root) or path.suffix != ".md":
            raise ValueError("Only Markdown inside the knowledge root is allowed")
        if path.stat().st_size > 100_000:
            raise ValueError("Document exceeds size limit")
        raw = path.read_bytes()
        total += len(raw)
        if total > 1_000_000:
            raise ValueError("Corpus exceeds size limit")
        content = raw.decode("utf-8").replace("\r\n", "\n")
        if not content.strip():
            raise ValueError("Documents cannot be empty")
        documents.append((metadata, content, hashlib.sha256(content.encode()).hexdigest()))
    return documents


def chunk_document(metadata, content, token_count):
    sections = []
    heading, lines, fenced = metadata.title, [], False
    for number, line in enumerate(content.splitlines(), 1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
        match = re.match(r"^#{1,6}\s+(.+)$", line) if not fenced else None
        if match:
            if any(text.strip() for _, text in lines):
                sections.append((heading, lines))
            heading, lines = match.group(1), []
        else:
            lines.append((number, line))
    if any(text.strip() for _, text in lines):
        sections.append((heading, lines))
    passages = []
    for heading, lines in sections:
        prefix = metadata.title + "\n" + heading + "\n"
        if token_count(prefix) > 60:
            raise ValueError("Heading exceeds the passage context budget")
        section = "\n".join(line for _, line in lines)
        words = list(re.finditer(r"\S+", section))
        start = 0
        while start < len(words):
            end = start
            while end < len(words):
                candidate = section[words[start].start() : words[end].end()]
                if token_count(prefix + candidate) > 180:
                    break
                end += 1
            if end == start:
                raise ValueError("A document token cannot fit the passage budget")
            body = section[words[start].start() : words[end - 1].end()]
            passages.append(
                {
                    "heading": heading,
                    "body": body,
                    "embedding_text": prefix + body,
                    "line_start": lines[0][0] + section[: words[start].start()].count("\n"),
                    "line_end": lines[0][0] + section[: words[end - 1].end()].count("\n"),
                }
            )
            if end == len(words):
                break
            start = max(start + 1, end - 12)
    if not passages:
        raise ValueError("Documents must contain body text")
    return passages


def prepare_corpus(root, embedder):
    documents = load_corpus(root)
    manifest = [
        {**metadata.model_dump(), "checksum": checksum} for metadata, _, checksum in documents
    ]
    revision = hashlib.sha256(
        json.dumps(
            {
                "manifest": manifest,
                "embedding": embedder.identity,
                "chunker": CHUNKER_VERSION,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    passages = []
    for metadata, content, checksum in documents:
        for ordinal, chunk in enumerate(chunk_document(metadata, content, embedder.token_count)):
            chunk_id = hashlib.sha256(f"{revision}:{metadata.id}:{ordinal}".encode()).hexdigest()
            passages.append(
                {
                    **chunk,
                    "id": chunk_id,
                    "revision_id": revision,
                    "document_id": metadata.id,
                    "source": metadata.path,
                    "title": metadata.title,
                    "service": metadata.service,
                    "application": metadata.application,
                    "environment": metadata.environment,
                    "release": metadata.release,
                    "document_checksum": checksum,
                    "token_count": embedder.token_count(chunk["embedding_text"]),
                }
            )
    if len(passages) > 500:
        raise ValueError("Corpus exceeds the passage limit")
    return revision, manifest, passages
