from app.core.config import Settings


def test_review_4_redis_network_calls_have_bounded_timeouts(monkeypatch):
    url = 'postgresql+psycopg://test_user:not-a-secret@localhost:5432/test_db'
    monkeypatch.setenv('DATABASE_URL', url)
    from app.main import create_app
    app = create_app(Settings(database_url=url))
    options = app.state.rate_limiter._client.connection_pool.connection_kwargs
    assert options.get('socket_timeout') == 1
    assert options.get('socket_connect_timeout') == 1
