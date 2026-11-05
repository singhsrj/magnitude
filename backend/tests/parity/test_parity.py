"""Cross-language parity: the Python engine must reproduce the TypeScript engine exactly.

Golden vectors come from `npm run golden` (scripts/generate-golden.ts).
Run: python3 -m unittest discover -s backend/tests/parity   (stdlib only)
"""
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "engine"))

from magnitude_engine import (  # noqa: E402
    DAILY_LENGTH, daily_problem, daily_seed, generate_problem, mulberry32,
    pick_skill, target_problem_rating, update_player,
)

GOLDEN = json.loads((pathlib.Path(__file__).parent / "golden.json").read_text())


def problem_dict(p):
    return {
        "id": p.id, "skill": p.skill, "rating": p.rating, "answer": p.answer,
        "left": {"text": p.left.text, "value": p.left.value},
        "right": {"text": p.right.text, "value": p.right.value},
    }


class Parity(unittest.TestCase):
    def test_rng_sequences(self):
        for case in GOLDEN["rng"]:
            rng = mulberry32(case["seed"])
            got = [rng() for _ in case["values"]]
            self.assertEqual(got, case["values"], f"seed {case['seed']}")

    def test_single_problems(self):
        for case in GOLDEN["problems"]:
            got = problem_dict(generate_problem(case["skill"], case["target"], mulberry32(case["seed"])))
            self.assertEqual(got, case["problem"], f"{case['skill']} seed {case['seed']} target {case['target']}")

    def test_problem_sequences_share_one_rng(self):
        for seq in GOLDEN["sequences"]:
            rng = mulberry32(seq["seed"])
            for i, (target, want) in enumerate(zip(seq["targets"], seq["problems"])):
                got = problem_dict(generate_problem(seq["skill"], target, rng))
                self.assertEqual(got, want, f"{seq['skill']} #{i}")

    def test_daily_sets(self):
        for day in GOLDEN["daily"]:
            self.assertEqual(daily_seed(day["date"]), day["seed"])
            self.assertEqual(len(day["problems"]), DAILY_LENGTH)
            for i, want in enumerate(day["problems"]):
                self.assertEqual(problem_dict(daily_problem(day["date"], i)), want, f"{day['date']} #{i}")

    def test_elo(self):
        for case in GOLDEN["elo"]:
            got = update_player(case["player"], case["problem"], case["correct"], case["timeMs"])
            want = case["result"]
            for field in ("next", "delta", "expected", "score"):
                self.assertAlmostEqual(getattr(got, field), want[field], places=9, msg=f"{case} {field}")

    def test_target_rating(self):
        for case in GOLDEN["targetRatings"]:
            self.assertAlmostEqual(target_problem_rating(case["player"]), case["target"], places=9)

    def test_pick_skill(self):
        for case in GOLDEN["picks"]:
            rng = mulberry32(case["seed"])
            got = [pick_skill(rng, case["skills"]) for _ in case["picks"]]
            self.assertEqual(got, case["picks"])


if __name__ == "__main__":
    unittest.main()
