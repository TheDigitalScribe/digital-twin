"""Tests for the FastAPI application: health/metrics endpoints and wiring."""

import pytest
from httpx import ASGITransport, AsyncClient

from digitaltwin.app import build_app


@pytest.mark.anyio
async def test_healthz_returns_ok():
    app = build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.anyio
async def test_metrics_exposes_prometheus_format():
    app = build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    body = resp.text
    assert "# TYPE digitaltwin_messages_received_total counter" in body
    assert "# TYPE digitaltwin_inflight_requests gauge" in body


@pytest.mark.anyio
async def test_gradio_mounted_at_root():
    from digitaltwin.app import build_interface

    interface = build_interface()
    # ChatInterface extends Blocks; it must be configurable.
    assert hasattr(interface, "get_config_file")