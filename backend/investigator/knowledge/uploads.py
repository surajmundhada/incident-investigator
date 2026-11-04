"""Bounded, explicit complete-corpus publication for a registered application scope."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import BaseModel, ConfigDict, Field, model_validator

from investigator.agent.security import redact
from investigator.catalog import Identifier

from .corpus import Document


class UploadDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,79}$")
    title: str = Field(min_length=3, max_length=120)
    service: Identifier
    markdown: str = Field(min_length=1, max_length=100_000)


class KnowledgeUpload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    application: Identifier
    configuration_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_revision: str | None = Field(pattern=r"^[a-f0-9]{64}$")
    documents: list[UploadDocument] = Field(min_length=1, max_length=50)
    replace_application_corpus: bool

    @model_validator(mode="after")
    def complete_corpus(self):
        if self.replace_application_corpus is not True:
            raise ValueError(
                "Explicitly acknowledge replacement of the complete application corpus"
            )
        if len({doc.id for doc in self.documents}) != len(self.documents):
            raise ValueError("Document IDs must be unique")
        if sum(len(doc.markdown.encode()) for doc in self.documents) > 1_000_000:
            raise ValueError("Corpus exceeds 1 MB")
        return self


def publish_upload(store, registry, upload):
    configuration = registry.revision(upload.configuration_revision)
    if configuration is None or configuration["application"] != upload.application:
        raise ValueError("A matching registered application configuration is required")
    services = set(configuration["services"]) | {"global"}
    if any(doc.service not in services for doc in upload.documents):
        raise ValueError("Runbooks must reference a registered service or global")
    with TemporaryDirectory(prefix="investigator-runbooks-") as directory:
        root = Path(directory)
        documents = []
        for doc in upload.documents:
            metadata = Document(
                id=doc.id,
                path=f"{doc.id}.md",
                title=redact(doc.title),
                service=doc.service,
                application=upload.application,
                environment=configuration["environment"],
                release=configuration["release"],
            )
            markdown = redact(doc.markdown).replace("\r\n", "\n")
            if len(markdown.encode()) > 100_000:
                raise ValueError("Document exceeds 100 KB")
            (root / metadata.path).write_text(markdown, encoding="utf-8")
            documents.append(metadata.model_dump())
        (root / "manifest.json").write_text(json.dumps({"documents": documents}), encoding="utf-8")
        return store.ingest(root, expected_revision=upload.expected_revision)
