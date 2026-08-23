from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


class WorkflowCadenceTests(unittest.TestCase):
    def test_company_foundation_runs_weekly_sunday_0615_ict(self) -> None:
        workflow = (WORKFLOWS / "update-data.yml").read_text(encoding="utf-8")

        self.assertIn("cron: '15 23 * * 6'", workflow)
        self.assertNotIn("cron: '15 23 * * *'", workflow)

    def test_root_data_writers_do_not_fan_out_on_merge_push(self) -> None:
        for name in ("update-data.yml", "update-sbv.yml", "update-market.yml"):
            workflow = (WORKFLOWS / name).read_text(encoding="utf-8")
            trigger_block = workflow[workflow.index("on:"):workflow.index("permissions:")]
            self.assertNotIn("push:", trigger_block, name)
            self.assertIn("schedule:", trigger_block, name)
            self.assertIn("workflow_dispatch:", trigger_block, name)

    def test_official_sbv_runs_daily_without_vnstock_secret(self) -> None:
        workflow = (WORKFLOWS / "update-sbv.yml").read_text(encoding="utf-8")
        company_workflow = (WORKFLOWS / "update-data.yml").read_text(encoding="utf-8")

        self.assertIn("cron: '15 23 * * *'", workflow)
        self.assertIn("group: rootvalue-data-write", workflow)
        self.assertNotIn("VNSTOCK_API_KEY", workflow)

        expected_order = [
            "python scripts/repair_sbv_official.py",
            "python scripts/build_sbv_history.py",
            "python scripts/publish_foundation.py",
            "python scripts/validate_data_contracts.py",
        ]
        offsets = [workflow.index(command) for command in expected_order]
        self.assertEqual(offsets, sorted(offsets))
        self.assertNotIn("python scripts/repair_sbv_official.py", company_workflow)
        self.assertNotIn("python scripts/build_sbv_history.py", company_workflow)

    def test_global_refresh_cannot_replace_pending_foundation_work(self) -> None:
        global_workflow = (WORKFLOWS / "update-global.yml").read_text(encoding="utf-8")
        company_workflow = (WORKFLOWS / "update-data.yml").read_text(encoding="utf-8")

        self.assertIn("group: rootvalue-global-write", global_workflow)
        self.assertNotIn("group: rootvalue-data-write", global_workflow)
        self.assertIn("group: rootvalue-data-write", company_workflow)

    def test_data_updaters_redeploy_pages_from_latest_main(self) -> None:
        pages = (WORKFLOWS / "pages.yml").read_text(encoding="utf-8")

        self.assertIn("workflow_run:", pages)
        for workflow_name in (
            "Rootvalue company foundation",
            "Rootvalue official SBV daily",
            "Rootvalue market flow",
            "Rootvalue global macro",
        ):
            self.assertIn(f"- {workflow_name}", pages)
        self.assertIn("ref: main", pages)
        self.assertIn("|| 'production'", pages)
        self.assertNotIn("github.event_name }}-${{ github.ref", pages)
        self.assertIn("python -m pip install -r requirements.txt", pages)
        self.assertNotIn("github.event.workflow_run.conclusion == 'success'", pages)

    def test_manual_runs_cannot_publish_a_feature_branch(self) -> None:
        for name in ("update-data.yml", "update-sbv.yml", "update-market.yml", "update-global.yml"):
            workflow = (WORKFLOWS / name).read_text(encoding="utf-8")
            checkout = workflow[workflow.index("- name: Checkout"):workflow.index("- name: Setup Python")]
            self.assertIn("ref: main", checkout, name)

        pages = (WORKFLOWS / "pages.yml").read_text(encoding="utf-8")
        self.assertIn("github.event_name == 'workflow_dispatch'", pages)
        self.assertGreaterEqual(pages.count("ref: main"), 2)

    def test_only_readiness_gate_is_allowed_to_continue_on_error(self) -> None:
        workflow = (WORKFLOWS / "update-sbv.yml").read_text(encoding="utf-8")
        contract_step = workflow.index("- name: Validate generated data contracts")
        readiness_step = workflow.index("- name: Report foundation readiness")
        commit_step = workflow.index("- name: Commit official SBV snapshot")

        self.assertNotIn("continue-on-error", workflow[contract_step:readiness_step])
        self.assertIn("continue-on-error: true", workflow[readiness_step:commit_step])


if __name__ == "__main__":
    unittest.main()
