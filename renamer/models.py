from dataclasses import dataclass
from pathlib import Path


@dataclass
class DocumentRef:
    doc_number: str
    doc_suffix: str
    citation: str
    line_no: int

    @property
    def doc_id(self) -> str:
        return f"{self.doc_number}{self.doc_suffix}"


@dataclass
class MatchResult:
    ref: DocumentRef
    matches: list[Path]
    reason: str


@dataclass
class CandidateDoc:
    path: Path
    name_tokens: set[str]
    content_tokens: set[str]
    norm_content: str


@dataclass
class DependencyStatus:
    tool: str
    required: bool
    found_path: str | None
    note: str
