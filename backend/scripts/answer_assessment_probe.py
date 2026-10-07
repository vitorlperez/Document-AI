"""Small paid live-provider probe using synthetic, non-customer evidence only.

Run from backend: .venv/bin/python scripts/answer_assessment_probe.py --env ../.env
No secrets, URLs, document content or generated answer are written in the report.
"""
import argparse
import json
import time
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from dotenv import dotenv_values

from app.knowledge.answer_assessment import (
    AssessmentSettings,
    JevAnswerAssessor,
    OfflineAnswerJudge,
)
from app.knowledge.questions import Evidence, QuestionResult

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--env', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
secrets = dotenv_values(args.env)
base = QuestionResult('A entrega será em 7 de outubro [1].', 'supported', [
    Evidence(uuid4(), 'Plano sintético', uuid4(), 'A entrega será em 7 de outubro.', None, '', 1.0)
], 'sufficient_evidence')
assessor = JevAnswerAssessor(secrets.get('TYPESAFE_API_KEY'), settings=AssessmentSettings(mode='shadow'))
judge = OfflineAnswerJudge(secrets.get('OPENAI_API_KEY'), model=secrets.get('AGENT_SYNTHESIS_MODEL') or 'gpt-5-mini')
runs = []
for label, text in [('supported', base.answer), ('unsupported', 'A entrega será em 31 de dezembro [1].')]:
    result = assessor.assess(question='Qual é o prazo de entrega?', result=replace(base, answer=text),
                             intent='ask_content', catalog=[])
    entry = {'case': label, 'assessment': result.resolved_context['assessment']}
    started = time.monotonic()
    try:
        entry['judge'] = judge.judge(question='Qual é o prazo de entrega?', result=result)
    except Exception as error:  # noqa: BLE001 - report only the safe error class
        entry['judge_error'] = type(error).__name__
    entry['judge_seconds'] = round(time.monotonic() - started, 3)
    runs.append(entry)
args.output.write_text(json.dumps({'synthetic_evidence': True, 'live_providers': True, 'runs': runs},
                                 ensure_ascii=False, indent=2))
print(json.dumps(runs, ensure_ascii=False, indent=2))
