"""Faults during a three-item discovery recover without discarding sibling content."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from cryptography.fernet import Fernet

from app.ingestion.google_drive import GoogleDriveDocumentProvider
from app.integrations.google_drive import (
    CredentialCipher,
    GoogleCredentials,
    GoogleDriveOAuthClient,
    RemoteFile,
)
from app.integrations.http import RemoteHttp
from app.integrations.notion import NotionDocumentProvider, NotionOAuthClient, NotionPage
from app.integrations.onedrive import (
    DeltaPage,
    MicrosoftGraphClient,
    OneDriveCipher,
    OneDriveCredentials,
    OneDriveDocumentProvider,
)


@pytest.mark.parametrize('provider,status', [('google_drive',429),('google_drive',503),('google_drive',403),('onedrive',429),('onedrive',503),('notion',429),('notion',503)])
def test_transient_fault_mid_sync_retains_all_three_documents(monkeypatch, provider, status):
    faults = []
    def get(url, **kwargs):
        middle = '/2' in url
        if middle and not faults:
            faults.append(status)
            return httpx.Response(status, headers={'Retry-After':'1'}, json={'error':{'errors':[{'reason':'userRateLimitExceeded'}]}}, request=httpx.Request('GET',url))
        if provider == 'notion':
            body = {'results':[{'type':'paragraph','paragraph':{'rich_text':[{'plain_text':'Approved content'}]}}], 'has_more':False}
            return httpx.Response(200,json=body,request=httpx.Request('GET',url))
        return httpx.Response(200,content=b'Approved content',request=httpx.Request('GET',url))
    monkeypatch.setattr(httpx,'get',get)
    waits = []
    client_http = RemoteHttp(sleep=waits.append, monotonic=lambda:0, jitter=lambda:1,
        is_retryable=lambda response: response.status_code == 403 and provider == 'google_drive')
    args = {'client_id':'id','client_secret':'secret','redirect_uri':'https://callback.test'}
    key = Fernet.generate_key().decode()
    selection = SimpleNamespace(kind='all_accessible', external_folder_id='', encrypted_delta_link=None, id=uuid4())
    if provider == 'google_drive':
        client = GoogleDriveOAuthClient(**args,http=client_http)
        monkeypatch.setattr(client,'list_all_files',lambda **kw:[RemoteFile(str(i),f'{i}.md','text/markdown',f'https://source.test/{i}',None) for i in range(1,4)])
        monkeypatch.setattr(client,'start_page_token',lambda **kw:'cursor')
        cipher = CredentialCipher(key)
        credentials = cipher.encrypt(GoogleCredentials('a','r',datetime.now(UTC)+timedelta(hours=1)))
        port = GoogleDriveDocumentProvider(client,cipher,extraction_workers=1)
    elif provider == 'onedrive':
        client = MicrosoftGraphClient(**args,http=client_http)
        monkeypatch.setattr(client,'delta',lambda **kw:DeltaPage([{'id':str(i),'name':f'{i}.md','file':{'mimeType':'text/markdown'}} for i in range(1,4)],'cursor'))
        cipher = OneDriveCipher(key)
        credentials = cipher.encrypt_credentials(OneDriveCredentials('a','r',datetime.now(UTC)+timedelta(hours=1)))
        port = OneDriveDocumentProvider(client,cipher)
    else:
        client = NotionOAuthClient(**args,http=client_http)
        monkeypatch.setattr(client,'list_pages',lambda **kw:[NotionPage(str(i),str(i),f'https://source.test/{i}',None) for i in range(1,4)])
        cipher = CredentialCipher(key)
        credentials = cipher.encrypt(GoogleCredentials('a',None,None))
        port = NotionDocumentProvider(client,cipher)
    result = port.discover(encrypted_credentials=credentials,selections=[selection])
    assert len(result.documents) == 3
    assert all(document.text == 'Approved content' and not document.error_code for document in result.documents)
    assert faults == [status] and waits
