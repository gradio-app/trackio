from dataclasses import dataclass
from typing import NamedTuple


class RunEntryTuple(NamedTuple):
    name: str
    id: int


@dataclass
class RunEntry:
    id: int
    name: str
    group_name: str | None
    created_at: str

    @classmethod
    def from_dict(cls, data: dict) -> "RunEntry":
        return cls(
            id=data["id"],
            name=data["name"],
            group_name=data["group_name"],
            created_at=data["created_at"],
        )

    def to_tuple(self) -> RunEntryTuple:
        return RunEntryTuple(self.name, self.id)
