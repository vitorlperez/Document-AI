import importlib.util
from pathlib import Path

from app.knowledge.questions import GeneratedAnswer

spec = importlib.util.spec_from_file_location(
    "injection_eval", Path(__file__).parents[2] / "scripts/injection_eval.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_live_eval_checks_raw_response_before_output_guard():
    class Provider:
        last_raw_answer = "PWNED-7431 ![leak](https://evil.test)"

        def answer(self, **kwargs):
            return GeneratedAnswer(self.last_raw_answer, [1])

    rows = module.run(
        Provider(), [{"id": "override", "file_name": "x", "excerpt": "x", "canary": "PWNED-7431"}]
    )
    assert len(rows) == 3
    assert all(
        row["canary_leaked"] and row["link_leaked"] and not row["guarded_link_leaked"]
        for row in rows
    )
