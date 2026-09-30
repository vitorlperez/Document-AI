"""Content synthesis contracts, complete passages and grounded equivalent citations."""
import json
from uuid import uuid4

import pytest

from app.core.scoping import OrganizationScope
from app.knowledge.questions import (
    AIProviderUnavailable,
    Evidence,
    OpenAIQuestionProvider,
    QuestionService,
)
from tests.unit.test_profile_retrieval import profile  # noqa: F401
from tests.unit.test_semantic_questions import session as semantic_session  # noqa: F401


def evidence(text, name='Version.pdf'):
    return Evidence(uuid4(), name, uuid4(), text, 1, 'https://drive.example.test/source', 0.8)


class MockLLM(OpenAIQuestionProvider):
    def __init__(self, answer, citations):
        super().__init__('simulated')
        self.output = {'answer': answer, 'citations': citations}
        self.body = None

    def _post(self, path, body):
        self.body = body
        return {'output': [{'content': [{'type': 'output_text', 'text': json.dumps(self.output)}]}]}


@pytest.mark.parametrize('stage', ['answer', 'synthesize_answer'])
def test_both_generation_stages_receive_shared_pool_and_complete_passages(stage):
    sources = [evidence(('Context. ' * 400) + 'Acme — 2021–2023.', 'Old.pdf'),
               evidence('Acme — 2021–2023. Beta — 2023–Present.', 'New.pdf')]
    provider = MockLLM('Acme — 2021–2023 [1]. Beta — 2023–Present [2].', [1, 2])
    if stage == 'answer':
        generated = provider.answer(question='Quais empresas e períodos?', evidence=sources)
    else:
        generated = provider.synthesize_answer(question='Quais empresas e períodos?', intent='ask_content',
                                                sources=sources, catalog=[])
    assert generated.citation_indexes == [1, 2]
    assert 'Cross-document evidence pool' in provider.body['input']
    assert all(item.excerpt in provider.body['input'] for item in sources)
    assert 'one sufficient source per factual item' in provider.body['instructions']
    assert 'relevant discrepancies in at most one sentence' in provider.body['instructions']
    assert 'requested information first' in provider.body['instructions']
    assert 'Read ALL passages' in provider.body['instructions']
    assert 'Blocks:' not in provider.body['instructions']
    assert provider.body['reasoning']['effort'] == 'low'


def test_identical_passages_collapse_citations_but_not_differing_dates():
    sources = [evidence('Acme — 2021–2023.'), evidence('Acme — 2021–2023.', 'Copy.pdf'),
               evidence('Acme — 2021–2024.', 'Changed.pdf')]
    provider = MockLLM('Acme — 2021–2023 [1][2]; outra versão registra 2024 [3].', [1, 2, 3])
    generated = provider.answer(question='Quando?', evidence=sources)
    assert generated.citation_indexes == [1, 3]
    assert '[2]' not in generated.text
    assert '[1]' in generated.text and '[3]' in generated.text
    assert 'equivalent_passages' in provider.body['input']


def test_equivalence_does_not_make_invalid_citations_valid():
    sources = [evidence('Fact.'), evidence('Fact.')]
    provider = MockLLM('Fact [1][9].', [1, 9])
    assert provider.answer(question='Fact?', evidence=sources).citation_indexes == [1, 9]


def test_repeated_legitimate_model_indices_do_not_reject_the_entire_answer():
    sources = [evidence('Acme 2021. Beta 2022.')]
    provider = MockLLM('Acme 2021 [1]. Beta 2022 [1].', [1, 1])
    result = provider.answer(question='Empresas e períodos?', evidence=sources)
    assert result.citation_indexes == [1]
    assert result.text.count('[1]') == 2


def test_explicit_per_document_synthesis_preserves_separate_citations():
    sources = [evidence('Acme — 2021–2023.'), evidence('Acme — 2021–2023.', 'Copy.pdf')]
    provider = MockLLM('::: file Version.pdf\nAcme [1].\n:::\n::: file Copy.pdf\nAcme [2].\n:::', [1, 2])
    result = provider.synthesize_answer(question='Resuma cada documento separadamente', intent='summarize_files',
                                        sources=sources, catalog=[])
    assert result.citation_indexes == [1, 2]


def test_real_profile_through_mocked_llm_is_complete_consolidated_and_linked(profile):  # noqa: F811
    session, org, user, folder, chunks = profile
    answer = ('- Wasion International — jan/2021–ago/2021 [1].\n'
              '- Cloudiabot — set/2021–jan/2023 [1].\n'
              '- Estoca — fev/2023–jun/2025 [1].\n'
              '- Allstacks — jun/2025–Present [1].')
    provider = MockLLM(answer, [1])
    provider.embed = lambda *, texts: [[1, 0] for _ in texts]
    result = QuestionService(session, provider).ask(scope=OrganizationScope(org.id), user_id=user.id,
        workspace_folder_id=folder.id, document_ids={chunks[0].document_id},
        question='Em quais empresas o Vitor trabalhou e quando?', answer_mode='content')
    assert all(item.text in provider.body['input'] for item in chunks)
    assert len(result.answer) < 400 and '::: file' not in result.answer
    assert result.citations[0].source_url
    assert all(name in result.answer for name in ('Wasion', 'Cloudiabot', 'Estoca', 'Allstacks'))


def test_timeout_keeps_links_without_dumping_full_documents(profile):  # noqa: F811
    session, org, user, folder, chunks = profile
    provider = MockLLM('', [])
    provider.embed = lambda *, texts: [[1, 0] for _ in texts]

    def unavailable(**kwargs):
        raise AIProviderUnavailable('simulated timeout')

    provider.answer = unavailable
    result = QuestionService(session, provider).ask(scope=OrganizationScope(org.id), user_id=user.id,
        workspace_folder_id=folder.id, document_ids={chunks[0].document_id}, question='Onde trabalhou?',
        answer_mode='content')
    assert len(result.answer) < 250
    assert 'indisponível' in result.answer
    assert result.citations[0].source_url
    assert all(item.text not in result.answer for item in chunks)
