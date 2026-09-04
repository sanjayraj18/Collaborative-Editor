from enum import StrEnum


class Role(StrEnum):
    NONE = "none"
    READER = "reader"
    WRITER = "writer"

    @property
    def can_read(self) -> bool:
        return self is not Role.NONE

    @property
    def can_write(self) -> bool:
        return self is Role.WRITER


class Visibility(StrEnum):
    """Mirrors the ck_documents_visibility constraint."""

    PRIVATE = "private"
    LINK = "link"
