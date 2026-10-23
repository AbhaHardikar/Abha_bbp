import unittest
import time

from fastapi.testclient import TestClient

from control_service import simulation_tick
from main import create_app


class ScheduleApiTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app("sqlite://")
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        self.app.state.engine.dispose()

    def test_seeded_schedule_has_equipment_and_visible_violations(self):
        response = self.client.get(
            "/api/schedule",
            params={"start_date": "2026-10-20", "end_date": "2026-11-10"},
        )

        self.assertEqual(response.status_code, 200)
        schedule = response.json()
        self.assertEqual(
            [item["name"] for item in schedule["equipment"]],
            ["1.5L", "15L", "20L", "75L", "1500L"],
        )
        self.assertEqual(len(schedule["batches"]), 3)
        self.assertEqual(len(schedule["unit_operations"]), 6)
        self.assertEqual(
            {item["rule"] for item in schedule["violations"]},
            {"equipment_conflict", "operation_sequence"},
        )
        self.assertTrue(
            all(
                len(violation["operation_ids"]) == 2
                for violation in schedule["violations"]
            )
        )

    def test_create_saves_an_operation_and_returns_its_violation(self):
        schedule = self.client.get(
            "/api/schedule",
            params={"start_date": "2026-10-20", "end_date": "2026-11-10"},
        ).json()
        beta = next(batch for batch in schedule["batches"] if batch["name"] == "Batch Beta")
        equipment = next(item for item in schedule["equipment"] if item["name"] == "1.5L")

        response = self.client.post(
            "/api/unit_operations",
            json={
                "name": "New Seed",
                "type": "Seed",
                "start_date": "2026-10-24",
                "end_date": "2026-10-26",
                "batch_id": beta["id"],
                "equipment_id": equipment["id"],
            },
        )

        self.assertEqual(response.status_code, 200)
        saved = response.json()
        self.assertGreater(saved["operation"]["id"], 0)
        self.assertIn("equipment_conflict", {item["rule"] for item in saved["violations"]})
        persisted_schedule = self.client.get(
            "/api/schedule",
            params={"start_date": "2026-10-20", "end_date": "2026-11-10"},
        ).json()
        self.assertIn(
            saved["operation"]["id"],
            {item["id"] for item in persisted_schedule["unit_operations"]},
        )

    def test_update_can_clear_a_seeded_equipment_violation(self):
        schedule = self.client.get(
            "/api/schedule",
            params={"start_date": "2026-10-20", "end_date": "2026-11-10"},
        ).json()
        beta_seed = next(
            operation
            for operation in schedule["unit_operations"]
            if operation["name"] == "Beta Seed"
        )

        response = self.client.put(
            f"/api/unit_operations/{beta_seed['id']}",
            json={"start_date": "2026-10-23"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("equipment_conflict", {item["rule"] for item in response.json()["violations"]})
        refreshed = self.client.get(
            "/api/schedule",
            params={"start_date": "2026-10-20", "end_date": "2026-11-10"},
        ).json()
        beta_conflicts = [
            item
            for item in refreshed["violations"]
            if item["rule"] == "equipment_conflict"
            and beta_seed["id"] in item["operation_ids"]
        ]
        self.assertEqual(beta_conflicts, [])

    def test_invalid_operation_dates_are_saved_with_a_named_violation(self):
        schedule = self.client.get(
            "/api/schedule",
            params={"start_date": "2026-10-20", "end_date": "2026-11-10"},
        ).json()
        beta = next(batch for batch in schedule["batches"] if batch["name"] == "Batch Beta")
        equipment = next(item for item in schedule["equipment"] if item["name"] == "20L")

        response = self.client.post(
            "/api/unit_operations",
            json={
                "name": "Out-of-bounds operation",
                "type": "Seed",
                "start_date": "2026-10-19",
                "end_date": "2026-10-21",
                "batch_id": beta["id"],
                "equipment_id": equipment["id"],
            },
        )

        self.assertEqual(response.status_code, 200)
        bounds = [
            item for item in response.json()["violations"] if item["rule"] == "batch_bounds"
        ]
        self.assertEqual(len(bounds), 1)
        self.assertIn("Out-of-bounds operation", bounds[0]["message"])

    def test_schedule_range_uses_exclusive_end_date(self):
        response = self.client.get(
            "/api/schedule",
            params={"start_date": "2026-10-23", "end_date": "2026-10-25"},
        )

        self.assertEqual(response.status_code, 200)
        operation_names = {item["name"] for item in response.json()["unit_operations"]}
        self.assertIn("Beta Seed", operation_names)
        self.assertNotIn("Beta Bioreactor", operation_names)

    def test_dependency_save_returns_a_violation(self):
        schedule = self.client.get(
            "/api/schedule",
            params={"start_date": "2026-10-20", "end_date": "2026-11-10"},
        ).json()
        operations = {item["name"]: item for item in schedule["unit_operations"]}

        response = self.client.post(
            "/api/unit_operation_dependencies",
            json={
                "from_unitop_id": operations["Beta Bioreactor"]["id"],
                "to_unitop_id": operations["Beta Seed"]["id"],
            },
        )

        self.assertEqual(response.status_code, 200)
        saved = response.json()
        self.assertIn("dependency", saved)
        self.assertIn("dependency", {item["rule"] for item in saved["violations"]})

    def test_completed_operation_cannot_be_moved_or_deleted(self):
        schedule = self.client.get(
            "/api/schedule",
            params={"start_date": "2026-10-20", "end_date": "2026-11-10"},
        ).json()
        operation_id = schedule["unit_operations"][0]["id"]
        completed = self.client.put(
            f"/api/unit_operations/{operation_id}",
            json={"status": "completed"},
        )
        self.assertEqual(completed.status_code, 200)

        moved = self.client.put(
            f"/api/unit_operations/{operation_id}",
            json={"start_date": "2026-10-21"},
        )
        deleted = self.client.delete(f"/api/unit_operations/{operation_id}")

        self.assertEqual(moved.status_code, 409)
        self.assertEqual(deleted.status_code, 409)

    def test_forecaster_reports_run_held_out_metrics_against_persistence(self):
        response = self.client.get("/api/forecaster/metrics")

        self.assertEqual(response.status_code, 200)
        metrics = response.json()
        self.assertEqual(metrics["split"]["train"], "run_A")
        self.assertEqual(metrics["split"]["validation"], "run_B")
        self.assertEqual(metrics["split"]["test"], "run_C")
        self.assertEqual(metrics["test"]["windows"], 2331)
        self.assertLess(metrics["test"]["rmse"], metrics["test"]["persistence_rmse"])
        self.assertEqual(len(metrics["test"]["by_horizon"]), 10)

    def test_ingest_persists_observations_and_append_only_forecasts(self):
        batches = []
        for minute in range(70):
            batches.append(
                {
                    "time_h": minute / 60,
                    "signal_name": "DO",
                    "value": 98 - minute * 0.05,
                    "unit": "%",
                }
            )
            batches.extend(
                [
                    {
                        "time_h": minute / 60,
                        "signal_name": "feed_rate",
                        "value": 1.0,
                        "unit": "mL/h",
                    },
                    {
                        "time_h": minute / 60,
                        "signal_name": "pH",
                        "value": 6.5,
                        "unit": "-",
                    },
                    {
                        "time_h": minute / 60,
                        "signal_name": "temp",
                        "value": 30.0,
                        "unit": "degC",
                    },
                ]
            )

        first = self.client.post("/ingest", json={"readings": batches[: 60 * 4]})
        second = self.client.post("/ingest", json={"readings": batches[60 * 4 :]})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["predictions_created"], 10)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["predictions_created"], 10)
        state = self.client.get("/api/control/state").json()
        self.assertEqual(len(state["predictions"]), 10)
        self.assertEqual(
            len(
                {
                    item["made_at_time_h"]
                    for item in state["predictions"]
                }
            ),
            1,
        )

    def test_command_validation_stores_rejections_and_blocks_pending_commands(self):
        started = self.client.post(
            "/api/simulator/start",
            json={
                "run_id": "run_A",
                "start_minute": 1000,
                "process_minutes_per_second": 0.01,
            },
        )
        self.assertEqual(started.status_code, 200)
        time.sleep(0.05)
        current_time = self.client.get("/api/control/state").json()["simulator"]["process_time_h"]

        invalid_commands = [
            {
                "setpoint_name": "feed_rate",
                "value": 31,
                "unit": "mL/h",
                "apply_at_time_h": current_time + 5 / 60,
            },
            {
                "setpoint_name": "feed_rate",
                "value": 5,
                "unit": "L/h",
                "apply_at_time_h": current_time + 5 / 60,
            },
            {
                "setpoint_name": "feed_rate",
                "value": 5,
                "unit": "mL/h",
                "apply_at_time_h": current_time - 0.01,
            },
            {
                "setpoint_name": "feed_rate",
                "value": 5,
                "unit": "mL/h",
                "apply_at_time_h": current_time + 1 / 60,
            },
        ]
        rejected = [
            self.client.post("/command", json=payload).json()
            for payload in invalid_commands
        ]
        self.assertTrue(all(not item["accepted"] for item in rejected))
        reasons = [item["reason"] for item in rejected]
        self.assertTrue(any("between 0.0 and 30.0" in reason for reason in reasons))
        self.assertTrue(any("must use mL/h" in reason for reason in reasons))
        self.assertTrue(any("earlier than" in reason for reason in reasons))
        self.assertTrue(any("actuator lag" in reason for reason in reasons))

        accepted_payload = {
            "setpoint_name": "feed_rate",
            "value": 20,
            "unit": "mL/h",
            "apply_at_time_h": current_time + 5 / 60,
        }
        accepted = self.client.post("/command", json=accepted_payload).json()
        pending = self.client.post("/command", json=accepted_payload).json()
        self.assertTrue(accepted["accepted"])
        self.assertFalse(pending["accepted"])
        self.assertIn("pending", pending["reason"])

        commands = self.client.get("/api/control/state").json()["commands"]
        self.assertEqual(len(commands), 6)
        self.assertEqual(sum(item["status"] == "rejected" for item in commands), 5)

    def test_relative_manual_command_anchors_delay_to_server_process_time(self):
        started = self.client.post(
            "/api/simulator/start",
            json={
                "run_id": "run_A",
                "start_minute": 1000,
                "process_minutes_per_second": 60,
            },
        )
        self.assertEqual(started.status_code, 200)

        response = self.client.post(
            "/api/control/commands",
            json={
                "value": 12,
                "unit": "mL/h",
                "apply_after_minutes": 5,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["accepted"])
        command = self.client.get("/api/control/state").json()["commands"][0]
        self.assertAlmostEqual(
            command["apply_at_time_h"] - command["issued_at_time_h"],
            5 / 60,
        )

    def test_simulator_applies_setpoint_and_delayed_do_response(self):
        started = self.client.post(
            "/api/simulator/start",
            json={
                "run_id": "run_A",
                "start_minute": 1000,
                "process_minutes_per_second": 0.01,
            },
        )
        self.assertEqual(started.status_code, 200)
        time.sleep(0.05)
        simulation_tick(
            self.app.state.engine,
            self.app.state.runs,
            self.app.state.forecaster,
            self.app.state.feed_limits,
        )
        state_before_command = self.client.get("/api/control/state").json()
        baseline_feed = next(
            reading["value"]
            for reading in reversed(state_before_command["readings"])
            if reading["signal_name"] == "feed_rate"
        )
        self.assertEqual(
            baseline_feed,
            self.app.state.runs["run_A"].samples[1001]["feed_rate"],
        )
        current_time = state_before_command["simulator"]["process_time_h"]
        command = self.client.post(
            "/command",
            json={
                "setpoint_name": "feed_rate",
                "value": 30,
                "unit": "mL/h",
                "apply_at_time_h": current_time + 5 / 60,
            },
        ).json()
        self.assertTrue(command["accepted"])

        for _ in range(5):
            simulation_tick(
                self.app.state.engine,
                self.app.state.runs,
                self.app.state.forecaster,
                self.app.state.feed_limits,
            )
        state_after_apply = self.client.get("/api/control/state").json()
        self.assertEqual(state_after_apply["simulator"]["current_feed_rate"], 30)
        deviation_at_apply = state_after_apply["simulator"]["do_deviation"]
        for _ in range(5):
            simulation_tick(
                self.app.state.engine,
                self.app.state.runs,
                self.app.state.forecaster,
                self.app.state.feed_limits,
            )
        state_after_response = self.client.get("/api/control/state").json()
        self.assertLess(
            state_after_response["simulator"]["do_deviation"],
            deviation_at_apply,
        )

    def test_configured_controller_emits_a_validated_feed_command(self):
        configured = self.client.put(
            "/api/control/config",
            json={"do_target_percent": 50, "dwell_minutes": 5},
        )
        self.assertEqual(configured.status_code, 200)
        self.assertTrue(configured.json()["configured"])
        started = self.client.post(
            "/api/simulator/start",
            json={
                "run_id": "run_A",
                "start_minute": 0,
                "process_minutes_per_second": 0.01,
            },
        )
        self.assertEqual(started.status_code, 200)
        time.sleep(0.05)

        for _ in range(59):
            simulation_tick(
                self.app.state.engine,
                self.app.state.runs,
                self.app.state.forecaster,
                self.app.state.feed_limits,
            )

        commands = self.client.get("/api/control/state").json()["commands"]
        controller_commands = [
            command for command in commands if command["source"] == "controller"
        ]
        self.assertEqual(len(controller_commands), 1)
        self.assertEqual(controller_commands[0]["status"], "pending")
        self.assertGreaterEqual(controller_commands[0]["value"], 0)
        self.assertLessEqual(controller_commands[0]["value"], 30)

    def test_manual_commands_obey_configured_dwell_time(self):
        self.client.put(
            "/api/control/config",
            json={"do_target_percent": 50, "dwell_minutes": 10},
        )
        self.client.post(
            "/api/simulator/start",
            json={
                "run_id": "run_A",
                "start_minute": 1000,
                "process_minutes_per_second": 0.01,
            },
        )
        time.sleep(0.05)
        current_time = self.client.get("/api/control/state").json()["simulator"]["process_time_h"]
        accepted = self.client.post(
            "/command",
            json={
                "setpoint_name": "feed_rate",
                "value": 18,
                "unit": "mL/h",
                "apply_at_time_h": current_time + 5 / 60,
            },
        ).json()
        self.assertTrue(accepted["accepted"])

        for _ in range(5):
            simulation_tick(
                self.app.state.engine,
                self.app.state.runs,
                self.app.state.forecaster,
                self.app.state.feed_limits,
            )
        current_time = self.client.get("/api/control/state").json()["simulator"]["process_time_h"]
        too_soon = self.client.post(
            "/command",
            json={
                "setpoint_name": "feed_rate",
                "value": 16,
                "unit": "mL/h",
                "apply_at_time_h": current_time + 5 / 60,
            },
        ).json()

        self.assertFalse(too_soon["accepted"])
        self.assertIn("10 process-minutes apart", too_soon["reason"])


if __name__ == "__main__":
    unittest.main()
