from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import get_settings
from backend.app.core.telemetry import operation


@lru_cache
def session_factory() -> sessionmaker[Session]:
    settings = get_settings()
    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        hide_parameters=True,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=10,
        pool_recycle=1800,
    )

    @event.listens_for(engine, "before_cursor_execute")
    def before(_conn, _cursor, _statement, _parameters, context, _many):  # type: ignore[no-untyped-def]
        context._smartrag_span = operation(
            "database.query", details={"db.system.name": engine.dialect.name}
        )
        context._smartrag_span.__enter__()

    @event.listens_for(engine, "after_cursor_execute")
    def after(_conn, _cursor, _statement, _parameters, context, _many):  # type: ignore[no-untyped-def]
        context._smartrag_span.__exit__(None, None, None)

    @event.listens_for(engine, "handle_error")
    def error(context):  # type: ignore[no-untyped-def]
        execution = context.execution_context
        if execution is not None and hasattr(execution, "_smartrag_span"):
            exc = context.original_exception
            execution._smartrag_span.__exit__(type(exc), exc, None)

    return sessionmaker(engine, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    with session_factory()() as session:
        yield session


def close_database() -> None:
    if session_factory.cache_info().currsize:
        engine = session_factory().kw["bind"]
        engine.dispose()
        session_factory.cache_clear()
