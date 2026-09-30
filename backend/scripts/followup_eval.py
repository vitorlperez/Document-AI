"""Real local corpus, classifier and embeddings; capture evidence or replay real LLM.

Uses the user's persisted companies answer as a frozen seed; never persists turns.
Duration/role cases add a clearly labelled fixed latest-job seed. Query vectors are
cached outside the repo for paired retrieval. All usage writes are rolled back.
Reports contain no credentials, URLs, or source excerpts.
"""
import argparse
import hashlib
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import build_engine
from app.core.scoping import OrganizationScope
from app.knowledge.agent import AgentLimits, AgentService
from app.knowledge.intent import INTENT_INSTRUCTIONS
from app.knowledge.models import Conversation, ConversationMessage, Document, DocumentChunk
from app.knowledge.questions import GeneratedAnswer, OpenAIQuestionProvider


class Capture(OpenAIQuestionProvider):
    def __init__(self, settings, cache, replay):
        super().__init__(settings.openai_api_key.get_secret_value(),
                         evidence_context_chars=settings.evidence_context_chars)
        self.cache, self.replay, self.sources, self.queries = cache, replay, [], []
        self.decision = None
        self.classifier_instructions_sha256 = None

    def _post(self, path, body):
        if body.get('text', {}).get('format', {}).get('name') == 'agent_intent':
            self.classifier_instructions_sha256 = hashlib.sha256(body['instructions'].encode()).hexdigest()
        return super()._post(path, body)

    def classify_intent(self, **kwargs):
        self.decision = super().classify_intent(**kwargs)
        return self.decision

    def embed(self, *, texts):
        self.queries.extend(texts)
        missing = [text for text in texts if text not in self.cache]
        if missing:
            self.cache.update(zip(missing, super().embed(texts=missing), strict=True))
        return [self.cache[text] for text in texts]

    def answer(self, *, question, evidence):
        self.sources = evidence
        if self.replay:
            return super().answer(question=question, evidence=evidence)
        return GeneratedAnswer('Captured evidence [1].', list(range(1, len(evidence) + 1)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--embedding-cache', type=Path, required=True)
    parser.add_argument('--replay', action='store_true')
    parser.add_argument('--fresh-sequence', action='store_true')
    args = parser.parse_args()
    settings = get_settings()
    cache = json.loads(args.embedding_cache.read_text()) if args.embedding_cache.exists() else {}
    report = {'mode': 'real_llm' if args.replay else 'captured_synthesis',
              'code_sha256': hashlib.sha256(Path(__import__('app.knowledge.agent', fromlist=['x']).__file__).read_bytes()).hexdigest(),
              'cases': []}
    report['intent_instructions_sha256'] = hashlib.sha256(INTENT_INSTRUCTIONS.encode()).hexdigest()
    with Session(build_engine(settings)) as session:
        seed = session.scalars(select(ConversationMessage).where(
            ConversationMessage.content == 'Em quais empresas o Vitor trabalhou e quando?'
        ).order_by(ConversationMessage.created_at.desc())).first()
        if seed is None:
            raise SystemExit('No companies transcript seed')
        conversation = session.get(Conversation, seed.conversation_id)
        scope, user_id = OrganizationScope(conversation.organization_id), conversation.user_id
        history = list(session.scalars(select(ConversationMessage).where(
            ConversationMessage.conversation_id == conversation.id,
            ConversationMessage.position >= seed.position,
            ConversationMessage.position <= seed.position + 1,
        ).order_by(ConversationMessage.position)))
        # Detached seed copies survive rollbacks unchanged.
        history = [ConversationMessage(role=m.role, content=m.content, context=m.context, response=m.response)
                   for m in history]
        profile = session.scalars(select(Document).where(
            Document.name == 'Profile.pdf', Document.organization_id == scope.organization_id,
            Document.index_status == 'indexed')).one()
        profile_id = profile.id
        positions = dict(session.execute(select(DocumentChunk.id, DocumentChunk.position).where(
            DocumentChunk.document_id == profile_id)).all())
        report['seed'] = 'persisted companies answer; latest-job fixture only for duration/role'
        if args.fresh_sequence:
            p = Capture(settings, cache, True)
            first, _, _ = AgentService(session, p, AgentLimits()).ask(
                scope=scope, user_id=user_id, question=history[0].content,
                providers=['google_drive'], mentions=[], history=[])
            history = [history[0], ConversationMessage(role='assistant', content=first.answer or '',
                response={'citations': [{'document_id': str(e.document_id)} for e in first.citations]})]
            report['first_turn'] = {'answer': first.answer, 'decision': p.decision,
                                   'linked_citations': sum(bool(e.source_url) for e in first.citations)}
            report['seed'] = 'fresh real first turn'
            session.rollback()
        for case in json.loads(args.cases.read_text()):
            messages = list(history)
            if case.get('after_latest'):
                messages.extend([
                    ConversationMessage(role='user', content='Qual foi o último emprego?'),
                    ConversationMessage(role='assistant',
                        content='O emprego mais recente do Vitor é Allstacks: Software Engineer, June 2025 - Present (8 months).',
                        response={'citations': [{'document_id': str(profile_id)}]}),
                ])
            p = Capture(settings, cache, args.replay)
            result, _, _ = AgentService(session, p, AgentLimits()).ask(
                scope=scope, user_id=user_id, question=case['question'], providers=['google_drive'],
                mentions=[], history=messages)
            selected = {positions[c] for e in p.sources
                        for c in (e.chunk_ids or (e.chunk_id,)) if c in positions}
            expected = set(case['expected_positions'])
            text = '\n'.join(e.excerpt for e in p.sources)
            facts = sum(fact in text for fact in case['facts'])
            report['cases'].append({
                'id': case['id'], 'question': case['question'], 'decision': p.decision,
                'classifier_instructions_sha256': p.classifier_instructions_sha256,
                'embedding_queries': p.queries, 'resolved_context': result.resolved_context,
                'expected': sorted(expected), 'selected_profile_positions': sorted(selected),
                'hits': len(expected & selected), 'expected_facts': len(case['facts']), 'visible_facts': facts,
                'sources': [{'name': e.document_name, 'score': e.score, 'chars': len(e.excerpt),
                             'chunk_count': len(e.chunk_ids or (e.chunk_id,))} for e in p.sources],
                'linked_citations': sum(bool(e.source_url) for e in result.citations),
                'answer': result.answer if args.replay else None, 'status': result.retrieval_status,
            })
            session.rollback()
    rows = report['cases']
    hits, expected = sum(r['hits'] for r in rows), sum(len(r['expected']) for r in rows)
    report['micro'] = {'hits': hits, 'expected': expected, 'recall': hits / expected,
                      'visible_facts': sum(r['visible_facts'] for r in rows),
                      'expected_facts': sum(r['expected_facts'] for r in rows)}
    args.embedding_cache.write_text(json.dumps(cache))
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({'output': str(args.output), 'micro': report['micro'],
                      'cases': [{'id': r['id'], 'hits': r['hits'], 'facts': r['visible_facts'],
                                 'decision': r['decision'], 'queries': r['embedding_queries'],
                                 'links': r['linked_citations']} for r in rows]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
