"""google_drive + google_drive_sa são UMA ferramenta ("Google Drive") para escopo, filtros e contagens."""
import pytest
from sqlalchemy import create_engine, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.access.principal import Principal
from app.access.scope import ScopedAccess
from app.api.ingestion import QuestionInput
from app.core.models import Base
from app.core.scoping import OrganizationScope
from app.integrations.models import DataSource
from app.knowledge.overview import folder_overview
from app.library.service import LibraryService
from app.library.tool_groups import provider_label, tool_group, tool_groups
from tests.access_helpers import seed_tenant


@pytest.fixture()
def factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_tool_group_maps_every_google_alias_to_one_key():
    assert {tool_group(p) for p in ("google", "google_drive", "google_drive_sa")} == {"google_drive"}
    assert tool_group("onedrive") == "onedrive"
    assert tool_groups(["google", "google_drive_sa", "notion"]) == {"google_drive", "notion"}


def test_provider_label_is_always_google_drive():
    assert provider_label("google_drive_sa") == provider_label("google_drive") == "Google Drive"


def test_question_input_accepts_the_sa_alias_as_the_same_tool():
    body = QuestionInput(question="oi", scope="selection", providers=["google_drive_sa"])
    assert body.providers == ["google_drive"]
    with pytest.raises(ValueError):  # mesma ferramenta duas vezes = duplicado
        QuestionInput(question="oi", scope="selection", providers=["google_drive", "google_drive_sa"])


def _make_sa(factory, tenant):
    with factory.begin() as session:
        session.execute(update(DataSource).where(DataSource.organization_id == tenant.organization_id)
                        .values(provider="google_drive_sa"))


@pytest.mark.parametrize("selected", [["google_drive"], ["google"], ["google_drive_sa"]])
def test_selecting_the_drive_tool_includes_the_shared_folder_connection(factory, selected):
    tenant = seed_tenant(factory, "A", "texto")
    _make_sa(factory, tenant)
    with factory() as session:
        selection = LibraryService(session).resolve_question_selection(
            scope=_scope(session, tenant), user_id=tenant.user_id, providers=selected, mentions=[])
    assert selection.folder_ids == [tenant.folder_id]


def _scope(session, tenant):
    return OrganizationScope(tenant.organization_id)


def test_scoped_access_and_overview_group_both_connections(factory):
    a, b = seed_tenant(factory, "A", "a"), seed_tenant(factory, "B", "b")
    _make_sa(factory, a)
    principal = Principal(a.organization_id, a.user_id, "api_key", frozenset({"search:read"}), None)
    with factory() as session:
        assert ScopedAccess(session, principal).providers() == ["google_drive"]
        overview = folder_overview(session, scope=_scope(session, a), user_id=a.user_id, providers=["google"])
        assert overview["document_count"] == 1
        # isolamento: cada org só enxerga as próprias pastas, mesmo com as duas conexões na mesma ferramenta
        mine = LibraryService(session).resolve_question_selection(
            scope=_scope(session, b), user_id=b.user_id, providers=["google_drive"], mentions=[])
        assert mine.folder_ids == [b.folder_id]


def test_library_root_of_the_shared_folder_connection_is_named_google_drive(factory):
    from app.library.models import LibraryNode
    tenant = seed_tenant(factory, "A", "a")
    _make_sa(factory, tenant)
    with factory.begin() as session:
        source = session.query(DataSource).filter_by(organization_id=tenant.organization_id).one()
        session.query(LibraryNode).filter_by(source_id=source.id, kind="source").update(
            {"name": "Google Drive (pasta compartilhada)"})
    with factory.begin() as session:
        source = session.query(DataSource).filter_by(organization_id=tenant.organization_id).one()
        root = LibraryService(session)._root(organization_id=tenant.organization_id, source=source)
        assert root.name == "Google Drive"


def _add_sa_root(factory, tenant, folder_name):
    from app.library.models import LibraryNode
    with factory.begin() as session:
        source = DataSource(organization_id=tenant.organization_id, provider="google_drive_sa",
                            encrypted_credentials="x", status="connected", connected_by_user_id=tenant.user_id)
        session.add(source)
        session.flush()
        root = LibraryNode(organization_id=tenant.organization_id, source_id=source.id, parent_id=None,
                           external_id="__company_library_source_root__", kind="source", name="Google Drive")
        session.add(root)
        session.flush()
        session.add(LibraryNode(organization_id=tenant.organization_id, source_id=source.id, parent_id=root.id,
                                external_id=folder_name, kind="folder", name=folder_name))
        return root.id


def test_children_of_the_drive_root_list_folders_of_both_connections_without_leaking_orgs(factory):
    from app.library.models import LibraryNode
    a, b = seed_tenant(factory, "A", "a"), seed_tenant(factory, "B", "b")
    _add_sa_root(factory, a, "Contratos")
    _add_sa_root(factory, b, "Segredo-B")
    with factory() as session:
        oauth_root = session.query(LibraryNode).filter_by(organization_id=a.organization_id, kind="source",
                                                          name="A").one()
        page = LibraryService(session).children(scope=_scope(session, a), user_id=a.user_id,
                                                parent_id=oauth_root.id, page=1, page_size=50)
    names = {item.name for item in page.items}
    # Spaces always enforce: the service-account root has no readable file yet, so its folder stays hidden
    assert "A plano.pdf" in names and "Contratos" not in names
    assert "Segredo-B" not in names and page.total == 1


def test_legacy_root_name_never_leaks_in_mention_paths(factory):
    """Raiz antiga '(pasta compartilhada)' ainda gravada no banco: o caminho mostrado ao usuário usa 'Google Drive'."""
    from app.library.models import LibraryNode
    tenant = seed_tenant(factory, "A", "a")
    root_id = _add_sa_root(factory, tenant, "Contratos")
    with factory.begin() as session:
        session.query(LibraryNode).filter_by(id=root_id).update({"name": "Google Drive (pasta compartilhada)"})
    with factory() as session:
        nodes = {n.id: n for n in session.query(LibraryNode).filter_by(organization_id=tenant.organization_id)}
        folder = next(n for n in nodes.values() if n.name == "Contratos")
        assert LibraryService._node_path(folder, nodes) == "Google Drive/Contratos"
