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
    next_gen_skills, normalize_time, round_rng, session_problem,
)

GOLDEN = json.loads((pathlib.Path(__file__).parent / "golden.json").read_text(encoding="utf-8"))


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

    # ---- Phase 4: practice sessions
    def test_round_rng(self):
        for case in GOLDEN["roundRngs"]:
            rng = round_rng(case["seed"], case["index"])
            self.assertEqual([rng() for _ in case["values"]], case["values"], f"index {case['index']}")

    def test_normalize_time(self):
        for case in GOLDEN["normalizeCases"]:
            self.assertEqual(normalize_time(case["ms"]), case["result"], f"{case['ms']}ms")

    def test_session_problems(self):
        for case in GOLDEN["sessionProblems"]:
            for index, want in enumerate(case["problems"]):
                got = problem_dict(session_problem(case["seed"], index, case["gen"]))
                self.assertEqual(got, want, f"seed {case['seed']} gen#{case['g']} round {index}")

    def test_session_replays(self):
        """Replay scripted sessions round by round: same problem, same grading, same ratings and gen skills."""
        for run in GOLDEN["sessionReplays"]:
            seed = run["seed"]
            gen = dict(run["startSkills"])
            rating = run["startRating"]
            skills = dict(run["startSkills"])
            for r in run["rounds"]:
                where = f"seed {seed} round {r['index']}"
                p = session_problem(seed, r["index"], gen)
                self.assertEqual((p.id, p.skill, p.rating, p.answer), (r["problemId"], r["skill"], r["problemRating"], r["answer"]), where)
                time_ms = r["timeMs"] if r["choice"] is None else normalize_time(r["rawMs"])
                self.assertEqual(time_ms, r["timeMs"], where)
                correct = r["choice"] is not None and r["choice"] == p.answer
                self.assertEqual(correct, r["correct"], where)
                rating = update_player(rating, p.rating, correct, time_ms).next
                skills[p.skill] = update_player(skills[p.skill], p.rating, correct, time_ms).next
                gen = next_gen_skills(gen, p.skill, p.rating, correct, time_ms)
                self.assertAlmostEqual(rating, r["rating"], places=9, msg=where)
                for s in skills:
                    self.assertAlmostEqual(skills[s], r["skills"][s], places=9, msg=f"{where} {s}")
                    self.assertAlmostEqual(gen[s], r["gen"][s], places=9, msg=f"{where} gen {s}")


if __name__ == "__main__":
    unittest.main()
