"""Replay a local content question, capturing actual requests; roll back all usage writes.

Full prompt/evidence captures stay in the explicitly chosen local output file.
No credentials or source URLs are recorded. Run inside an isolated PYTHONPATH
in the API container to compare versions without restarting the stack.
"""
import argparse
import hashlib
import json
import time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import build_engine
from app.core.scoping import OrganizationScope
from app.knowledge.agent import AgentLimits, AgentService
from app.knowledge.models import Conversation, ConversationMessage
from app.knowledge.questions import OpenAIQuestionProvider, _response_output_text


class Capture(OpenAIQuestionProvider):
    def __init__(self, settings, cache):
        super().__init__(settings.openai_api_key.get_secret_value(),
                         evidence_context_chars=settings.evidence_context_chars)
        self.cache, self.requests, self.sources, self.outputs = cache, [], [], []
        self.decision = None

    def _post(self, path, body):
        if path == '/v1/responses':
            self.requests.append(body)
        result = super()._post(path, body)
        if path == '/v1/responses':
            self.outputs.append(_response_output_text(result))
        return result

    def classify_intent(self, **kwargs):
        self.decision = super().classify_intent(**kwargs)
        return self.decision

    def embed(self, *, texts):
        missing = [text for text in texts if text not in self.cache]
        if missing:
            self.cache.update(zip(missing, super().embed(texts=missing), strict=True))
        return [self.cache[text] for text in texts]

    def answer(self, *, question, evidence):
        self.sources = evidence
        return super().answer(question=question, evidence=evidence)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--embedding-cache', type=Path, required=True)
    parser.add_argument('--question', default='Em quais empresas o Vitor trabalhou e quando?')
    args = parser.parse_args()
    settings = get_settings()
    cache = json.loads(args.embedding_cache.read_text()) if args.embedding_cache.exists() else {}
    provider = Capture(settings, cache)
    with Session(build_engine(settings)) as session:
        seed = session.scalars(select(ConversationMessage).where(
            ConversationMessage.role == 'user'
        ).order_by(ConversationMessage.created_at.desc())).first()
        if seed is None:
            raise SystemExit('No local conversation to resolve authorized scope')
        conversation = session.get(Conversation, seed.conversation_id)
        scope, user_id = OrganizationScope(conversation.organization_id), conversation.user_id
        started = time.monotonic()
        result, _, _ = AgentService(session, provider, AgentLimits()).ask(
            scope=scope, user_id=user_id, question=args.question,
            providers=['google_drive'], mentions=[], history=[])
        report = {
            'question': args.question, 'intent': provider.decision,
            'resolved_context': result.resolved_context, 'answer': result.answer,
            'answer_chars': len(result.answer or ''), 'elapsed_seconds': time.monotonic() - started,
            'citations': [{'name': e.document_name, 'has_link': bool(e.source_url)}
                          for e in result.citations],
            'evidence': [{'name': e.document_name, 'chars': len(e.excerpt),
                          'sha256': hashlib.sha256(e.excerpt.encode()).hexdigest(),
                          'chunks': len(e.chunk_ids or (e.chunk_id,))} for e in provider.sources],
            'requests': provider.requests,
            'outputs': provider.outputs,
        }
        session.rollback()
    args.embedding_cache.write_text(json.dumps(cache))
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k not in ('requests', 'outputs')},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
