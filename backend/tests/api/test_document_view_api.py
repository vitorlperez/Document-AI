"""In-chat file viewing: scope, content types, streaming and provider failures with simulated connectors."""
import io
from uuid import UUID, uuid4

import httpx
import pytest

from app.api.document_view import content_disposition, safe_filename
from app.ingestion.extraction.mime import DOCX, GOOGLE_DOC, PDF, SHEETS
from app.integrations.errors import SourceRemoteUnauthorized
from app.integrations.google_drive import GoogleItemTooLarge
from app.integrations.http import RemoteThrottled
from app.integrations.models import DataSource
from app.knowledge.file_access import DocumentFileFetcher, FileAccessError, OpenedFile
from app.knowledge.models import Document, DocumentChunk
from tests.api.test_multiscope_questions_api import ask, corpus  # noqa: F401
from tests.api.test_text_search_api import login, search_api  # noqa: F401


class FakeFetcher:
    def __init__(self, payload: bytes = b'%PDF-1.7 fake', content_type: str = PDF, error: FileAccessError | None = None):
        self.payload, self.content_type, self.error = payload, content_type, error
        self.opened: list[str] = []
        self.preview = 'https://contoso.sharepoint.example/embed?token=short'

    def open(self, document, source):
        self.opened.append(source.provider)
        if self.error:
            raise self.error
        return OpenedFile(io.BytesIO(self.payload), self.content_type, len(self.payload), document.name)

    def preview_url(self, document, source, page):
        return self.preview if source.provider == 'onedrive' else None


def citation_for(client, org, provider='google_drive'):
    citations = ask(client, org, scope='organization').json()['citations']
    return next(item for item in citations if item['source_provider'] == provider)


def test_file_streams_original_with_safe_headers(corpus):  # noqa: F811 - imported pytest fixture
    client, _, _, org, _, _ = corpus
    client.app.state.document_file_fetcher = FakeFetcher(b'%PDF-1.7 ' + b'x' * 600_000)
    cite = citation_for(client, org)
    response = client.get(f"/organizations/{org}/documents/{cite['document_id']}/file")
    assert response.status_code == 200
    assert response.content.startswith(b'%PDF-1.7') and len(response.content) == 600_009
    assert response.headers['content-type'] == PDF
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['content-disposition'].startswith('inline; filename="google_drive campaign.pdf"')
    assert response.headers['cache-control'] == 'private, max-age=60'
    assert response.headers['content-length'] == '600009'
    assert 'sandbox' in response.headers['content-security-policy']


def test_file_is_hidden_outside_the_members_scope(corpus):  # noqa: F811 - imported pytest fixture
    client, factory, _, org, _, _ = corpus
    fake = FakeFetcher()
    client.app.state.document_file_fetcher = fake
    cite = citation_for(client, org)
    base = f"/organizations/{org}/documents/{cite['document_id']}"
    assert client.get(f"/organizations/{uuid4()}/documents/{cite['document_id']}/file").status_code == 404
    assert client.get(f"/organizations/{org}/documents/{uuid4()}/file").status_code == 404
    with factory.begin() as session:  # a document whose folder belongs to someone else's tenant
        session.get(Document, UUID(cite['document_id'])).organization_id = uuid4()
    assert client.get(f'{base}/file').status_code == 404
    assert client.get(f'{base}/chunks').status_code == 404
    assert client.get(f'{base}/view').status_code == 404
    assert client.post(f'{base}/preview', json={}).status_code == 404
    assert fake.opened == []  # the connector is never reached for an unauthorized document


def test_file_is_hidden_from_a_non_member(corpus):  # noqa: F811 - imported pytest fixture
    client, _, gateway, org, _, _ = corpus
    cite = citation_for(client, org)
    client.app.state.document_file_fetcher = FakeFetcher()
    login(client, gateway, code='stranger', email='stranger@example.test', subject='stranger')
    for suffix in ('file', 'chunks', 'view'):
        assert client.get(f"/organizations/{org}/documents/{cite['document_id']}/{suffix}").status_code == 404


def test_file_requires_a_session(corpus):  # noqa: F811 - imported pytest fixture
    client, _, _, org, _, _ = corpus
    cite = citation_for(client, org)
    client.cookies.clear()
    assert client.get(f"/organizations/{org}/documents/{cite['document_id']}/file").status_code == 401


@pytest.mark.parametrize(('error', 'status', 'code'), [
    (FileAccessError(409, 'source_access_denied'), 409, 'source_access_denied'),
    (FileAccessError(404, 'source_file_missing'), 404, 'source_file_missing'),
    (FileAccessError(413, 'file_too_large'), 413, 'file_too_large'),
    (FileAccessError(415, 'viewer_not_supported'), 415, 'viewer_not_supported'),
    (FileAccessError(429, 'source_throttled', retry_after=12), 429, 'source_throttled'),
])
def test_provider_errors_become_clear_codes(corpus, error, status, code):  # noqa: F811 - imported pytest fixture
    client, _, _, org, _, _ = corpus
    client.app.state.document_file_fetcher = FakeFetcher(error=error)
    cite = citation_for(client, org)
    response = client.get(f"/organizations/{org}/documents/{cite['document_id']}/file")
    assert response.status_code == status and response.json() == {'detail': code}
    if status == 429:
        assert response.headers['retry-after'] == '12'


def test_file_failures_are_logged_with_provider_and_code(corpus, caplog):  # noqa: F811 - imported pytest fixture
    client, _, _, org, _, _ = corpus
    client.app.state.document_file_fetcher = FakeFetcher(error=FileAccessError(409, 'source_access_denied'))
    cite = citation_for(client, org)
    with caplog.at_level('WARNING'):
        response = client.get(f"/organizations/{org}/documents/{cite['document_id']}/file")
    assert response.status_code == 409
    record = next(item for item in caplog.records if getattr(item, 'event', None) == 'document_file_failed')
    assert (record.code, record.status_code, record.provider) == ('source_access_denied', 409, 'google_drive')
    assert record.document_id == cite['document_id']


def test_view_metadata_and_preview(corpus):  # noqa: F811 - imported pytest fixture
    client, factory, _, org, _, _ = corpus
    client.app.state.document_file_fetcher = FakeFetcher()
    cite = citation_for(client, org)
    view = client.get(f"/organizations/{org}/documents/{cite['document_id']}/view").json()
    assert view['mime_type'] == PDF and view['file_available'] is True and view['office_preview'] is False
    assert view['source_provider'] == 'google_drive'
    notion = citation_for(client, org, 'notion')
    assert client.get(f"/organizations/{org}/documents/{notion['document_id']}/view").json()['file_available'] is False
    with factory.begin() as session:
        document = session.get(Document, UUID(cite['document_id']))
        source = session.query(DataSource).filter_by(provider='google_drive').one()
        source.provider = 'onedrive'
        document.mime_type = DOCX
    preview = client.post(f"/organizations/{org}/documents/{cite['document_id']}/preview", json={'page': 3})
    assert preview.json() == {'url': 'https://contoso.sharepoint.example/embed?token=short'}
    assert client.get(f"/organizations/{org}/documents/{cite['document_id']}/view").json()['office_preview'] is True
    assert client.post(f"/organizations/{org}/documents/{cite['document_id']}/preview", json={'page': 0}).status_code == 422


def test_chunks_are_ordered_paginated_and_can_land_on_the_cited_chunk(corpus):  # noqa: F811 - imported pytest fixture
    client, factory, _, org, _, _ = corpus
    cite = citation_for(client, org, 'notion')
    with factory.begin() as session:
        template = session.get(DocumentChunk, UUID(cite['chunk_id']))
        for position in range(1, 5):
            session.add(DocumentChunk(
                organization_id=UUID(str(org)), workspace_folder_id=template.workspace_folder_id, document_id=template.document_id,
                position=position, text=f'chunk {position}', search_text=f'chunk {position}', page_number=position + 1,
            ))
    url = f"/organizations/{org}/documents/{cite['document_id']}/chunks"
    first = client.get(url, params={'limit': 2}).json()
    assert [c['position'] for c in first['chunks']] == [0, 1] and first['total'] == 5 and first['has_more'] is True
    assert first['chunks'][1]['page_number'] == 2
    second = client.get(url, params={'limit': 2, 'offset': 2}).json()
    assert [c['position'] for c in second['chunks']] == [2, 3]
    last = client.get(url, params={'limit': 2, 'offset': 4}).json()
    assert last['has_more'] is False and len(last['chunks']) == 1
    with factory() as session:
        wanted = session.query(DocumentChunk).filter_by(document_id=UUID(cite['document_id']), position=3).one().id
    around = client.get(url, params={'limit': 2, 'around_chunk_id': str(wanted)}).json()
    assert around['offset'] == 2 and wanted.hex in {c['id'].replace('-', '') for c in around['chunks']}
    assert client.get(url, params={'limit': 1000}).status_code == 422


def test_filename_is_sanitized():
    assert '/' not in safe_filename('../../etc/pass"wd\r\n.pdf') and '"' not in safe_filename('a"b')
    header = content_disposition('Relatório "final"\r\nSet-Cookie: x.pdf')
    assert '\r' not in header and '\n' not in header and header.count('"') == 2
    assert "filename*=UTF-8''Relat%C3%B3rio" in header
    assert safe_filename('') == 'arquivo'


class Recorder:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def google_provider(*, read=None, export=None):
    seen = Recorder(calls=[])
    def remote_call(encrypted, call):
        seen.calls.append(encrypted)
        return call(Recorder(access_token='t'))
    client = Recorder(
        read_file=lambda credentials, remote_file: read(remote_file) if read else io.BytesIO(b'%PDF'),
        export_pdf=lambda credentials, file_id: export(file_id) if export else io.BytesIO(b'%PDF-export'),
    )
    return Recorder(client=client, _remote_call=remote_call, seen=seen)


def make_document(mime):
    return Document(organization_id=uuid4(), workspace_folder_id=uuid4(), external_file_id='ext-1', name='Plano.pdf',
                    mime_type=mime, source_url='https://x', content_hash='a' * 64, index_status='indexed')


def make_source(provider, status='connected'):
    return DataSource(id=uuid4(), organization_id=uuid4(), provider=provider, encrypted_credentials='cipher',
                      status=status, connected_by_user_id=uuid4())


def fetcher(provider):
    return DocumentFileFetcher(None, None, provider_factory=lambda key, source_id: provider)


def test_real_fetcher_google_binary_and_native_export():
    google = google_provider()
    opened = fetcher(google).open(make_document(PDF), make_source('google_drive'))
    assert (opened.content_type, opened.size, opened.filename) == (PDF, 4, 'Plano.pdf') and opened.stream.read() == b'%PDF'
    native = fetcher(google).open(make_document(GOOGLE_DOC), make_source('google_drive'))
    assert (native.content_type, native.filename, native.stream.read()) == (PDF, 'Plano.pdf.pdf', b'%PDF-export')
    assert fetcher(google).open(make_document(SHEETS), make_source('google_drive')).content_type == PDF
    assert google.seen.calls == ['cipher'] * 3


@pytest.mark.parametrize(('provider', 'mime'), [
    ('notion', PDF), ('clickup', PDF), ('google_drive', 'text/csv'), ('onedrive', 'application/vnd.ms-excel'),
])
def test_real_fetcher_refuses_types_the_viewer_cannot_render(provider, mime):
    boom = google_provider(read=lambda *_: pytest.fail('must not download'))
    with pytest.raises(FileAccessError) as caught:
        fetcher(boom).open(make_document(mime), make_source(provider))
    assert caught.value.status_code == 415


@pytest.mark.parametrize(('raised', 'status', 'code'), [
    (SourceRemoteUnauthorized(), 409, 'source_access_denied'),
    (GoogleItemTooLarge('exportSizeLimitExceeded'), 413, 'file_too_large'),
    (RemoteThrottled(7), 429, 'source_throttled'),
    (httpx.HTTPStatusError('x', request=httpx.Request('GET', 'https://x'), response=httpx.Response(404)), 404, 'source_file_missing'),
    (httpx.HTTPStatusError('x', request=httpx.Request('GET', 'https://x'), response=httpx.Response(403)), 409, 'source_access_denied'),
    (httpx.HTTPStatusError('x', request=httpx.Request('GET', 'https://x'), response=httpx.Response(500)), 502, 'source_unavailable'),
    (httpx.ConnectError('down'), 502, 'source_unavailable'),
])
def test_real_fetcher_maps_connector_failures(raised, status, code):
    def fail(*_):
        raise raised
    with pytest.raises(FileAccessError) as caught:
        fetcher(google_provider(read=fail)).open(make_document(PDF), make_source('google_drive'))
    assert (caught.value.status_code, caught.value.code) == (status, code)


def test_real_fetcher_requires_a_connected_source():
    with pytest.raises(FileAccessError) as caught:
        fetcher(google_provider()).open(make_document(PDF), make_source('google_drive', status='reauth_required'))
    assert caught.value.code == 'source_access_denied'


class FakeSession:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1


def microsoft_provider(*, refreshed=None, preview=None):
    provider = Recorder(updated_encrypted_credentials=refreshed, items=[])
    provider._credentials = lambda encrypted: Recorder(access_token='t')
    def read_file(credentials, item_id):
        provider.items.append(item_id)
        return io.BytesIO(b'PK docx bytes')
    provider.client = Recorder(read_file=read_file, preview_url=lambda credentials, item_id, page: preview(item_id, page))
    return provider


def test_real_fetcher_microsoft_download_and_refreshed_credentials_are_persisted():
    provider, session = microsoft_provider(refreshed='new-cipher'), FakeSession()
    source = make_source('sharepoint')
    opened = DocumentFileFetcher(None, session, provider_factory=lambda *_: provider).open(make_document(DOCX), source)
    assert opened.content_type == DOCX and opened.stream.read() == b'PK docx bytes'
    assert provider.items == ['ext-1'] and source.encrypted_credentials == 'new-cipher' and session.commits == 1


def test_real_fetcher_preview_returns_none_instead_of_raising():
    pages = []
    ok = microsoft_provider(preview=lambda item, page: pages.append(page) or 'https://embed.example/x')
    source = make_source('onedrive')
    assert DocumentFileFetcher(None, FakeSession(), provider_factory=lambda *_: ok).preview_url(make_document(DOCX), source, 4) == 'https://embed.example/x'
    assert pages == [4]
    def unauthorized(*_):
        raise SourceRemoteUnauthorized()
    broken = microsoft_provider(preview=unauthorized)
    assert DocumentFileFetcher(None, FakeSession(), provider_factory=lambda *_: broken).preview_url(make_document(DOCX), source, 1) is None
    assert DocumentFileFetcher(None, FakeSession(), provider_factory=lambda *_: ok).preview_url(make_document(DOCX), make_source('google_drive'), 1) is None
    assert DocumentFileFetcher(None, FakeSession(), provider_factory=lambda *_: ok).preview_url(make_document('text/csv'), source, 1) is None
