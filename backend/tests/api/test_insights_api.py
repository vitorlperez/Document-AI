from uuid import uuid4

from app.knowledge.models import ConversationMessage, Document
from tests.api.test_multiscope_questions_api import ask, corpus  # noqa: F401
from tests.api.test_text_search_api import login, search_api  # noqa: F401


def test_insights_aggregate_metadata_without_conversation_text(corpus):  # noqa: F811
    client, factory, _, org, folders, _ = corpus
    conv = ask(client, org, scope="organization").json()["conversation_id"]
    msg = client.get(f"/organizations/{org}/conversations/{conv}").json()["messages"][-1]["id"]
    client.put(f"/organizations/{org}/conversations/{conv}/messages/{msg}/feedback", json={"vote": "down"})
    with factory.begin() as session:
        session.query(Document).filter_by(workspace_folder_id=folders["notion"]).update(
            {"index_status": "failed", "error_code": "file_encrypted"})
    response = client.get(f"/organizations/{org}/insights")
    assert response.status_code == 200
    body = response.json()
    assert body["answers"]["total_answers"] == 1
    assert body["answers"]["feedback"] == {"up": 0, "down": 1}
    notion = next(f for f in body["folders"] if f["workspace_id"] == str(folders["notion"]))
    assert notion["failed"] == 1 and notion["error_codes"] == {"file_encrypted": 1}
    assert {"kind": "reprocess", "workspace_id": str(folders["notion"])} in notion["actions"]
    assert any(s["kind"] == "reprocess" for s in body["suggestions"])
    with factory() as session:
        texts = [m.content for m in session.query(ConversationMessage)]
    assert not any(text and text in response.text for text in texts)


def test_insights_require_admin(corpus):  # noqa: F811
    client, _, _, org, _, _ = corpus
    assert client.get(f"/organizations/{uuid4()}/insights").status_code == 403
    assert client.get(f"/organizations/{org}/insights?days=0").status_code == 422
