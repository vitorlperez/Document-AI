from app.knowledge.agent import AgentLimits, FlowModels
from app.knowledge.agent_eval import EvalCase, run_case
from app.knowledge.questions import AIProviderUnavailable
from tests.unit.test_agent_flow import IntentProvider, _folder_with_files
from tests.unit.test_semantic_questions import session as semantic_session  # noqa: F401


def test_offline_judge_records_failure_and_rolls_back(semantic_session):  # noqa: F811
    scope, user, folder, _ = _folder_with_files(semantic_session)
    class Judge:
        def judge(self, **kwargs):
            assert kwargs['result'].citations
            raise AIProviderUnavailable('must never be copied into report')
    run = run_case(semantic_session, IntentProvider(),
                   EvalCase('one', 'Liste arquivos', ['google_drive'], [('folder', folder.id)], []),
                   scope=scope, user_id=user.id, limits=AgentLimits(), models=FlowModels(), judge=Judge())
    assert run.error is None
    assert run.judge is None and run.judge_error == 'AIProviderUnavailable'
    assert run.assessment['mode'] == 'shadow'
    assert not semantic_session.in_transaction()
