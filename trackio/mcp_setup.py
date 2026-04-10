from contextlib import asynccontextmanager


@asynccontextmanager
async def mcp_lifespan_context(app):
    yield
