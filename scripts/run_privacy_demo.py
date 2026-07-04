from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sentinel.audit.store import AuditStore
from sentinel.privacy.engine import PrivacyEngine
from sentinel.privacy.vault import EntityVault


def main() -> None:
    db_path = Path("data/local/demo.sqlite")
    engine = PrivacyEngine(vault=EntityVault(db_path), audit_store=AuditStore(db_path))
    transcript = Path("data/samples/dangerous.txt").read_text(encoding="utf-8")
    analysis = engine.analyze(transcript, session_id="demo")
    print("Risk:", analysis.risk_level.value)
    print("Blocked:", analysis.counts.blocked)
    print("Pseudonymized:", analysis.counts.pseudonymized)
    print("\nSafe payload:\n")
    print(analysis.safe_content)


if __name__ == "__main__":
    main()
