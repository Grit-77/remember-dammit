"""Create a fresh synthetic vault and exercise the real provider-free engine.

This is a core demonstration, not a recording of any native AI client.
Install the package from this checkout before running it.
"""

import argparse
import json
from pathlib import Path
import sys

from remember_dammit.errors import VaultError
from remember_dammit.retrieval import context, search
from remember_dammit.storage import Vault


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", required=True, help="A new directory for synthetic data")
    args = parser.parse_args()
    destination = Path(args.vault)
    if destination.exists() or destination.is_symlink():
        print(json.dumps({"error": "destination_exists", "message": "Choose a new demo directory."}))
        return 1
    try:
        vault = Vault.initialize(destination)
        original = vault.put(title="Initial brief", body="Use SendGrid for transactional email.",
                             kind="source", scope="project:atlas", operation_id="demo-original-source")
        first = vault.put(title="Email provider", body="Use SendGrid for Atlas email.",
                          scope="project:atlas", sources=[original["id"]], operation_id="demo-decision")
        correction = vault.put(title="Owner correction", body="Use Postmark for Atlas email.",
                               kind="source", scope="project:atlas", operation_id="demo-correction-source")
        vault.correct(first["id"], expected_revision=first["revision"], title="Email provider",
                      body="Use Postmark for Atlas email.", sources=[correction["id"]],
                      operation_id="demo-correction")
        reopened = Vault(destination)
        report = {
            "demonstration": "real local core; no native harness or model invoked",
            "vault_id": reopened.vault_id,
            "context": context(reopened, "SendGrid email", project="atlas", budget_bytes=8000),
            "history_states": [item["state"] for item in reopened.history(first["id"])],
            "other_project_records": len(search(reopened, "email", project="beacon")["records"]),
        }
        sys.stdout.buffer.write((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        return 0
    except VaultError as error:
        print(json.dumps({"error": error.code, "message": error.message}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
