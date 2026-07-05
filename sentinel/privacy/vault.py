from __future__ import annotations

import re
import secrets
from pathlib import Path
from typing import Any

from sentinel.db.schema import connect_database, initialize_database
from sentinel.domain.privacy import SensitiveEntityType


PREFIX_BY_TYPE = {
    SensitiveEntityType.PERSON: "PERSON",
    SensitiveEntityType.ORGANIZATION: "ORG",
    SensitiveEntityType.CLIENT: "CLIENT",
    SensitiveEntityType.EMAIL: "EMAIL",
    SensitiveEntityType.PHONE: "PHONE",
    SensitiveEntityType.MONEY: "MONEY",
    SensitiveEntityType.DATE: "DATE",
    SensitiveEntityType.INTERNAL_PROJECT: "PROJECT",
    SensitiveEntityType.CLASSIFICATION: "CLASSIFICATION",
    SensitiveEntityType.CODE_NAME: "CODE",
    SensitiveEntityType.TIME: "TIME",
    SensitiveEntityType.ROLE: "ROLE",
    SensitiveEntityType.FACILITY: "FACILITY",
    SensitiveEntityType.SECURITY_CONTROL: "CONTROL",
    SensitiveEntityType.SECRET_REFERENCE: "SECRET",
    SensitiveEntityType.CONNECTION_STRING: "CONN",
}

NON_RECONSTRUCTABLE_PREFIXES = ("SECRET_", "CONN_")


class EntityVault:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        return connect_database(self.db_path)

    def _init_db(self) -> None:
        initialize_database(self.db_path)

    def get_or_create(self, session_id: str, entity_type: SensitiveEntityType, original_value: str) -> str:
        with self._connect() as conn:
            existing = conn.execute(
                """
                SELECT placeholder FROM entity_vault
                WHERE session_id = ? AND entity_type = ? AND original_value = ?
                """,
                (session_id, entity_type.value, original_value),
            ).fetchone()
            if existing:
                return str(existing["placeholder"])

            placeholder = self._new_placeholder(conn, entity_type)
            conn.execute(
                """
                INSERT INTO entity_vault (session_id, entity_type, original_value, placeholder)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, entity_type.value, original_value, placeholder),
            )
            return placeholder

    def resolve(self, placeholder: str) -> str | None:
        clean = placeholder.strip("[]")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT original_value FROM entity_vault WHERE placeholder = ?",
                (clean,),
            ).fetchone()
        return str(row["original_value"]) if row else None

    def mappings_for_session(self, session_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT entity_type, original_value, placeholder
                FROM entity_vault
                WHERE session_id = ?
                ORDER BY LENGTH(original_value) DESC
                """,
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def mappings(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT entity_type, original_value, placeholder
                FROM entity_vault
                ORDER BY LENGTH(original_value) DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def rewrite_text_for_session(self, session_id: str, text: str) -> str:
        return self._rewrite_text(text, self.mappings_for_session(session_id))

    def rewrite_text(self, text: str) -> str:
        return self._rewrite_text(text, self.mappings())

    def _rewrite_text(self, text: str, mappings: list[dict[str, Any]]) -> str:
        replacements: list[tuple[str, str]] = []
        for row in mappings:
            original = str(row["original_value"]).strip()
            placeholder = f"[{row['placeholder']}]"
            if original:
                replacements.append((original, placeholder))

            if row["entity_type"] == SensitiveEntityType.PERSON.value:
                first_name = original.split()[0] if original.split() else ""
                if len(first_name) > 2:
                    replacements.append((first_name, placeholder))

        rewritten = text
        seen: set[tuple[str, str]] = set()
        for original, placeholder in sorted(replacements, key=lambda item: len(item[0]), reverse=True):
            if (original, placeholder) in seen:
                continue
            seen.add((original, placeholder))
            pattern = re.compile(rf"(?<!\w){re.escape(original)}(?!\w)")
            rewritten = pattern.sub(placeholder, rewritten)
        return rewritten

    def reconstruct(self, text: str, allowed_placeholders: set[str] | None = None) -> str:
        with self._connect() as conn:
            rows = conn.execute("SELECT placeholder, original_value FROM entity_vault").fetchall()
        reconstructed = text
        for row in rows:
            placeholder = str(row["placeholder"])
            if allowed_placeholders is not None and placeholder not in allowed_placeholders:
                continue
            if allowed_placeholders is None and placeholder.startswith(NON_RECONSTRUCTABLE_PREFIXES):
                continue
            reconstructed = reconstructed.replace(f"[{placeholder}]", str(row["original_value"]))
        return reconstructed

    def delete_mapping(self, placeholder: str) -> bool:
        clean = placeholder.strip("[]")
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM entity_vault WHERE placeholder = ?", (clean,))
            return cursor.rowcount > 0

    def _new_placeholder(self, conn: sqlite3.Connection, entity_type: SensitiveEntityType) -> str:
        prefix = PREFIX_BY_TYPE.get(entity_type, entity_type.value)
        while True:
            placeholder = f"{prefix}_{secrets.token_hex(2).upper()}"
            exists = conn.execute(
                "SELECT 1 FROM entity_vault WHERE placeholder = ?",
                (placeholder,),
            ).fetchone()
            if not exists:
                return placeholder
