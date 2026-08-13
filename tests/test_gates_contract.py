import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "gates_contract.py"
SPEC = importlib.util.spec_from_file_location("gates_contract", SCRIPT)
gates_contract = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(gates_contract)


V2 = {
    "generation": "v2",
    "group": "ci-scope-v2-trusted",
    "labels": ["self-hosted", "macOS", "ARM64", "ci-scope-v2"],
}


class RoutingContractTests(unittest.TestCase):
    def assert_invalid(self, routing, message, **kwargs):
        with self.assertRaisesRegex(gates_contract.RoutingContractError, message):
            gates_contract.validate_routing(routing, **kwargs)

    def test_v2_happy_path_and_optional_canary_inputs(self):
        routing = {
            **V2,
            "workflow-contract-version": "2",
            "trust-fixture-mode": "canary-only",
        }
        self.assertEqual(
            gates_contract.validate_routing(routing, environment="canary"),
            {
                **V2,
                "workflow-contract-version": "v2",
                "trust-fixture-mode": "canary-only",
            },
        )

    def test_v1_default_remains_valid(self):
        self.assertEqual(
            gates_contract.validate_routing({"generation": "v1", "group": "ci-scope", "labels": ["self-hosted"]})[
                "generation"
            ],
            "v1",
        )

    def test_required_routing_fields_and_shapes(self):
        for field in ("generation", "group", "labels"):
            routing = dict(V2)
            routing.pop(field)
            self.assert_invalid(routing, rf"{field}: .*required")
        self.assert_invalid([], "routing: must be an object")
        self.assert_invalid({**V2, "labels": "self-hosted"}, "labels: must be an array")

    def test_group_and_labels_are_nonempty_bounded_and_unique(self):
        self.assert_invalid({**V2, "group": " "}, "group: must not be empty")
        self.assert_invalid({**V2, "labels": ["self-hosted", " "]}, r"labels\[1\]: must not be empty")
        self.assert_invalid(
            {**V2, "labels": ["ci-scope-v2", "CI-SCOPE-V2"]},
            "labels: must not contain duplicates",
        )
        self.assert_invalid({**V2, "labels": ["x"] * 33}, "labels: must contain at most 32")
        self.assert_invalid({**V2, "group": "g" * 101}, "group: must be at most 100")

    def test_v2_requires_dedicated_group_and_label(self):
        self.assert_invalid({**V2, "group": "other"}, "group: v2 requires")
        self.assert_invalid({**V2, "labels": ["self-hosted"]}, "labels: v2 requires")

    def test_unknown_generation_fails_closed(self):
        self.assert_invalid({**V2, "generation": "v3"}, "generation: .*unknown generations")
        self.assert_invalid({**V2, "generation": []}, "generation: must be a string")

    def test_v1_and_v2_routing_inputs_cannot_mix(self):
        self.assert_invalid({**V2, "generation": "v1"}, "v1 and v2")
        self.assert_invalid(
            {
                "generation": "v2",
                "routing-generation": "v1",
                "group": V2["group"],
                "labels": V2["labels"],
            },
            "mixed routing-generation and generation",
        )

    def test_workflow_contract_version_is_bounded_and_matches_generation(self):
        self.assertEqual(
            gates_contract.validate_routing({**V2, "workflow-contract-version": "v2"})["workflow-contract-version"],
            "v2",
        )
        self.assert_invalid(
            {**V2, "workflow-contract-version": "v1"},
            "workflow-contract-version: must match",
        )
        self.assert_invalid(
            {**V2, "workflow-contract-version": "latest"},
            "workflow-contract-version: must be",
        )
        self.assert_invalid(
            {**V2, "workflow-contract-version": None},
            "workflow-contract-version: must be a string",
        )

    def test_canary_trust_fixture_mode_is_not_a_production_escape_hatch(self):
        self.assert_invalid(
            {**V2, "trust-fixture-mode": "canary-only"},
            "trust-fixture-mode: canary-only is forbidden",
        )
        self.assert_invalid(
            {**V2, "trust-fixture-mode": "always"},
            "trust-fixture-mode: only canary-only",
        )
        self.assert_invalid(
            {
                "generation": "v1",
                "group": "ci-scope",
                "labels": ["self-hosted"],
                "trust-fixture-mode": "canary-only",
            },
            "trust-fixture-mode: canary-only requires",
            environment="canary",
        )

    def test_production_rejects_arbitrary_untrusted_group(self):
        self.assert_invalid(
            {"generation": "v1", "group": "attacker-group", "labels": ["self-hosted"]},
            "production rejects arbitrary",
        )
        self.assertEqual(
            gates_contract.validate_routing(
                {
                    "generation": "v1",
                    "group": "attacker-group",
                    "labels": ["self-hosted"],
                },
                trusted_input=True,
            )["group"],
            "attacker-group",
        )

    def test_workflow_input_aliases_are_canonicalised(self):
        self.assertEqual(
            gates_contract.validate_routing(
                {
                    "routing-generation": "v2",
                    "runner-group": V2["group"],
                    "runner-labels": V2["labels"],
                }
            ),
            V2,
        )


if __name__ == "__main__":
    unittest.main()
