"""PersonRegistry: in-memory lookup for canonical persons and aliases.

Loads persons and aliases from SQLite once per extraction session
and provides fast case-insensitive lookup for entity matching.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from objlib.entities.models import AliasRecord, PersonRecord

if TYPE_CHECKING:
    from objlib.database import Database

logger = logging.getLogger(__name__)


class PersonRegistry:
    """In-memory registry of canonical persons and their aliases.

    Loaded from SQLite person/person_alias tables. The canonical list
    is small (15 people, ~50 aliases) so in-memory lookup is instant.

    Usage:
        registry = PersonRegistry(db)
        person = registry.get_person("ayn-rand")
        aliases = registry.lookup_alias("Peikoff")
        is_blocked = registry.is_blocked("Smith")
    """

    def __init__(self, db: Database) -> None:
        self._persons: dict[str, PersonRecord] = {}
        self._aliases: dict[str, list[AliasRecord]] = {}  # alias_text_lower -> records
        self._blocked: set[str] = set()
        self._load(db)

    def _load(self, db: Database) -> None:
        """Load all persons and aliases from the database."""
        # Load persons
        rows = db.conn.execute(
            "SELECT person_id, canonical_name, type FROM person"
        ).fetchall()
        for row in rows:
            self._persons[row["person_id"]] = PersonRecord(
                person_id=row["person_id"],
                canonical_name=row["canonical_name"],
                type=row["type"],
            )

        # Load aliases
        alias_rows = db.conn.execute(
            "SELECT alias_text, person_id, alias_type, is_blocked FROM person_alias"
        ).fetchall()
        for row in alias_rows:
            record = AliasRecord(
                alias_text=row["alias_text"],
                person_id=row["person_id"],
                alias_type=row["alias_type"],
                is_blocked=bool(row["is_blocked"]),
            )
            key = row["alias_text"].casefold()
            if key not in self._aliases:
                self._aliases[key] = []
            self._aliases[key].append(record)

            if record.is_blocked:
                self._blocked.add(key)

        logger.debug(
            "PersonRegistry loaded: %d persons, %d alias keys, %d blocked",
            len(self._persons),
            len(self._aliases),
            len(self._blocked),
        )

    def get_person(self, person_id: str) -> PersonRecord | None:
        """Look up a person by their slug ID."""
        return self._persons.get(person_id)

    def lookup_alias(self, text: str) -> list[AliasRecord]:
        """Look up aliases matching the given text (case-insensitive).

        Returns all alias records for the given text, which may include
        blocked aliases. Callers should check is_blocked if needed.
        """
        return self._aliases.get(text.casefold(), [])

    def is_blocked(self, text: str) -> bool:
        """Check if a text string is a blocked alias."""
        return text.casefold() in self._blocked

    def all_persons(self) -> list[PersonRecord]:
        """Return all canonical persons."""
        return list(self._persons.values())

    def all_aliases(self) -> list[AliasRecord]:
        """Return all alias records (flattened)."""
        result: list[AliasRecord] = []
        for records in self._aliases.values():
            result.extend(records)
        return result

    def get_canonical_name(self, person_id: str) -> str | None:
        """Get the canonical name for a person_id, or None if not found."""
        person = self._persons.get(person_id)
        return person.canonical_name if person else None
