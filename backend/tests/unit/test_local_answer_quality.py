from dataclasses import replace

import pytest

from app.knowledge.answer_assessment import AssessmentSettings, JevAnswerAssessor
from tests.unit.test_answer_assessment import answer


def evaluate(monkeypatch, result, intent='ask_content'):
    assessor = JevAnswerAssessor('existing-key', settings=AssessmentSettings(mode='shadow'))
    monkeypatch.setattr(assessor, '_post', lambda *args: pytest.fail('external transfer'))
    output = assessor.assess(question='Q', result=result, intent=intent, catalog=[])
    assert output.answer == result.answer
    assert output.citations == result.citations
    return output.resolved_context['assessment']['local_evaluation']


def test_local_citation_integrity_pass_has_explicit_semantic_limit(monkeypatch):
    quality = evaluate(monkeypatch, answer())
    assert quality['outcome'] == 'pass'
    assert quality['issues'] == []
    assert quality['semantic_grounding'] == 'not_evaluated'
    assert quality['checks']['citation_numbers_valid'] is True


def test_local_reports_dangling_reference_without_echoing_content(monkeypatch):
    quality = evaluate(monkeypatch, replace(answer(), answer='Private answer [99].'))
    assert quality['outcome'] == 'warn'
    assert 'invalid_citation_reference' in quality['issues']
    assert 'Private' not in str(quality)


@pytest.mark.parametrize('result,issue', [
    (replace(answer(), answer='   '), 'empty_answer'),
    (replace(answer(), citations=[]), 'missing_document_evidence'),
    (replace(answer(), citations=[replace(answer().citations[0], excerpt=' ')]), 'empty_cited_excerpt'),
])
def test_local_reports_actionable_integrity_issues(monkeypatch, result, issue):
    quality = evaluate(monkeypatch, result)
    assert quality['outcome'] == 'warn'
    assert issue in quality['issues']


@pytest.mark.parametrize('intent,confidence', [('greeting', 'supported'), ('list_files', 'supported'),
                                              ('ask_content', 'insufficient_evidence')])
def test_non_document_or_honest_insufficiency_needs_no_citation(monkeypatch, intent, confidence):
    quality = evaluate(monkeypatch, replace(answer(), answer='Sem conteúdo para responder.',
                                           confidence=confidence, citations=[]), intent)
    assert quality['outcome'] == 'pass'


@pytest.mark.parametrize('marker', ['[0]', '[99]', '[999999999]', '(fonte 0)',
                                  '(fontes 1, 99 e 1)', '[' + '9' * 5000 + ']'])
def test_out_of_range_canonical_and_bracket_markers(monkeypatch, marker):
    quality = evaluate(monkeypatch, replace(answer(), answer='Prazo ' + marker))
    assert 'invalid_citation_reference' in quality['issues']


def test_canonical_source_marker_passes(monkeypatch):
    quality = evaluate(monkeypatch, replace(answer(), answer='Prazo (fontes 1 e 1).'))
    assert quality['outcome'] == 'pass'


def test_local_failure_cannot_break_default_delivery(monkeypatch):
    assessor = JevAnswerAssessor('key', settings=AssessmentSettings(mode='off'))
    monkeypatch.setattr(assessor, '_post', lambda *args: pytest.fail('external transfer'))
    result = replace(answer(), citations=[replace(answer().citations[0], excerpt=None)])
    output = assessor.assess(question='Q', result=result, intent='ask_content', catalog=[])
    assert output.answer == result.answer
    assert output.citations == result.citations
    assert output.resolved_context['assessment']['reason'] == 'disabled'
    quality = output.resolved_context['assessment']['local_evaluation']
    assert quality == {'kind': 'citation_integrity', 'outcome': 'error',
                       'issues': ['evaluation_failed'], 'semantic_grounding': 'not_evaluated'}
