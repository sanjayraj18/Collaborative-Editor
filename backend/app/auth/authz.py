from enum import StrEnum

class Role(StrEnum):
    NONE="none"
    READER="reader"
    WRITER="writer"

    @property
    def can_read(self) -> bool:
        return self is not Role.NONE

    @property
    def can_write(self) -> bool:
        return self is Role.WRITER
