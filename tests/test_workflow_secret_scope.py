from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
SECRET_ASSIGNMENT = "VNSTOCK_API_KEY: ${{ secrets.VNSTOCK_API_KEY }}"


def secret_step_names(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    step_names: list[str] = []

    for index, line in enumerate(lines):
        if line.strip() != SECRET_ASSIGNMENT:
            continue

        # A job-level env key is indented six spaces in these workflows; a
        # step-level env key is nested beneath the step and indented ten.
        indentation = len(line) - len(line.lstrip())
        if indentation < 10:
            raise AssertionError(
                f"{path.name}:{index + 1}: VNSTOCK_API_KEY must be scoped to a step"
            )

        for prior in reversed(lines[:index]):
            match = re.match(r"^\s{6}- name:\s*(.+?)\s*$", prior)
            if match:
                step_names.append(match.group(1))
                break
        else:
            raise AssertionError(
                f"{path.name}:{index + 1}: secret assignment is not inside a named step"
            )

    return step_names


class WorkflowSecretScopeTests(unittest.TestCase):
    def test_data_key_is_available_only_to_provider_fetch_steps(self) -> None:
        self.assertEqual(
            secret_step_names(WORKFLOWS / "update-data.yml"),
            [
                "Build 8Y company + macro foundation",
                "Repair empty financial statements",
            ],
        )

    def test_market_key_is_available_only_to_provider_fetch_step(self) -> None:
        self.assertEqual(
            secret_step_names(WORKFLOWS / "update-market.yml"),
            ["Refresh market flow and investigation picks"],
        )

    def test_official_sbv_workflow_has_no_vnstock_secret(self) -> None:
        self.assertEqual(secret_step_names(WORKFLOWS / "update-sbv.yml"), [])


if __name__ == "__main__":
    unittest.main()
