import math
from dataclasses import replace
from uuid import uuid4

import pytest

from app.knowledge.answer_assessment import (
    AssessmentSettings,
    JevAnswerAssessor,
    OfflineAnswerJudge,
)
from app.knowledge.questions import AIProviderUnavailable, Evidence, QuestionResult
from tests.unit.test_semantic_questions import session as semantic_session  # noqa: F401


def answer():
    return QuestionResult('O prazo é 7 de outubro [1].', 'supported', [
        Evidence(uuid4(), 'Plano', uuid4(), 'Entrega: 7 de outubro.', None, '', 1.0)
    ], 'sufficient_evidence', resolved_context={'existing': True})


def test_shadow_preserves_cited_answer_and_records_rejection(monkeypatch):
    assessor = JevAnswerAssessor('key')
    monkeypatch.setattr(assessor, '_post', lambda body: {'answers': {
        k: {'noul': 0.1} for k in ('grounded', 'relevant', 'safe')
    }})
    result = assessor.assess(question='Qual prazo?', result=answer(), intent='ask_content', catalog=[])
    assert result.answer == answer().answer
    assert result.resolved_context['existing'] is True
    assert result.resolved_context['assessment']['outcome'] == 'reject'
    assert result.confidence == 'supported'
    assert result.citations


@pytest.mark.parametrize('value', [None, True, '0.9', -1, 2, math.nan, math.inf])
def test_invalid_scores_cannot_approve(monkeypatch, value):
    assessor = JevAnswerAssessor('key', settings=AssessmentSettings(mode='enforce'))
    monkeypatch.setattr(assessor, '_post', lambda body: {'answers': {
        k: {'noul': value} for k in ('grounded', 'relevant', 'safe')
    }})
    result = assessor.assess(question='Prazo?', result=answer(), intent='ask_content', catalog=[])
    assert result.answer is None and not result.citations
    assert result.resolved_context['assessment']['outcome'] == 'unavailable'


@pytest.mark.parametrize('mode,key', [('off', 'key'), ('shadow', None)])
def test_no_credentials_or_off_never_calls_provider(monkeypatch, mode, key):
    assessor = JevAnswerAssessor(key, settings=AssessmentSettings(mode=mode))
    monkeypatch.setattr(assessor, '_post', lambda body: pytest.fail('unexpected network'))
    result = assessor.assess(question='Prazo?', result=answer(), intent='ask_content', catalog=[])
    assert result.answer == answer().answer


def test_no_answer_and_oversize_skip_http(monkeypatch):
    assessor = JevAnswerAssessor('key')
    monkeypatch.setattr(assessor, '_post', lambda body: pytest.fail('unexpected network'))
    absent = replace(answer(), answer=None, citations=[])
    assert assessor.assess(question='Q', result=absent, intent='ask_content', catalog=[]).answer is None
    result = assessor.assess(question='Q' * 30000, result=answer(), intent='ask_content', catalog=[])
    assert result.resolved_context['assessment']['reason'] == 'input_too_large'


def test_error_is_shadow_only_and_content_not_in_metadata(monkeypatch):
    assessor = JevAnswerAssessor('key')
    def fail(body):
        raise AIProviderUnavailable('sensitive contents')
    monkeypatch.setattr(assessor, '_post', fail)
    result = assessor.assess(question='Prazo?', result=answer(), intent='ask_content', catalog=[])
    assert result.answer == answer().answer
    assert 'sensitive' not in str(result.resolved_context['assessment'])


def test_offline_judge_parses_validated_scores(monkeypatch):
    judge = OfflineAnswerJudge('key', model='existing-model')
    monkeypatch.setattr(judge, '_post', lambda path, body: {'output': [{'content': [{'type': 'output_text', 'text':
        '{"grounding": 1, "relevance": 0.8, "completeness": 0.5}'}]}]})
    assert judge.judge(question='Prazo?', result=answer())['grounding'] == 1


def test_stage_runs_after_cite_on_authorized_sources(semantic_session):  # noqa: F811 - imported pytest fixture
    from app.knowledge.agent import AgentLimits, AgentService
    from tests.unit.test_agent_flow import IntentProvider, _folder_with_files

    scope, user, folder, _ = _folder_with_files(semantic_session)
    captured = []
    class Assessor:
        def assess(self, **kwargs):
            captured.append(kwargs)
            assert kwargs['result'].citations
            assert kwargs['result'].answer
            return kwargs['result']
    agent = AgentService(semantic_session, IntentProvider(), AgentLimits(), answer_assessor=Assessor())
    result, _, _ = agent.ask(scope=scope, user_id=user.id, question='Liste e resuma arquivos',
                            providers=['google_drive'], mentions=[('folder', folder.id)], history=[])
    assert len(captured) == 1
    assert captured[0]['result'].citations == result.citations


def test_assessment_deadline_is_bounded_by_request(monkeypatch):
    import time

    from app.knowledge.questions import _REQUEST_DEADLINE, request_deadline
    assessor = JevAnswerAssessor('key')
    deadlines = []
    def post(body):
        deadlines.append(_REQUEST_DEADLINE.get())
        return {'answers': {k: {'noul': .95} for k in ('grounded', 'relevant', 'safe')}}
    monkeypatch.setattr(assessor, '_post', post)
    deadline = time.monotonic() + .1
    with request_deadline(deadline):
        result = assessor.assess(question='Prazo?', result=answer(), intent='ask_content', catalog=[])
    assert deadlines == [deadline]
    assert result.resolved_context['assessment']['outcome'] == 'pass'


@pytest.mark.parametrize('output', ['{}', '{"grounding":true,"relevance":1,"completeness":1}',
                                   '{"grounding":1.1,"relevance":1,"completeness":1}'])
def test_offline_judge_invalid_output_does_not_approve(monkeypatch, output):
    judge = OfflineAnswerJudge('key', model='model')
    monkeypatch.setattr(judge, '_post', lambda *args: {'output': [{'content': [
        {'type': 'output_text', 'text': output}]}]})
    with pytest.raises((ValueError, TypeError, KeyError)):
        judge.judge(question='Q', result=answer())


def test_catalog_cannot_self_validate_generated_answer_or_send_internal_ids():
    from app.knowledge.answer_assessment import assessment_state
    state = assessment_state(question='Q', result=answer(), intent='list_files', catalog=[
        {'name': 'summarize_documents', 'result': {'answer': 'invented fact'}},
        {'name': 'catalog_inventory', 'result': {'total': 1, 'items': [
            {'name': 'Plano', 'kind': 'file', 'id': 'internal-id', 'source_url': 'private-url',
             'excerpt': 'unnecessary text'}]}}
    ])
    assert state['catalog'] == [{'total': 1, 'items': [{'name': 'Plano', 'kind': 'file'}]}]
