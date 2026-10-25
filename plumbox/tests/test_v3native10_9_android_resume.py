from pathlib import Path
import re


ROOT = Path(__file__).parents[1]
APP_JS = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")


def test_bootstrap_retries_instead_of_aborting_after_first_ingress_failure():
    assert "async function loadInitialDataWithRetry()" in APP_JS
    assert "while (!state.initialized && !state.authExpired)" in APP_JS
    assert "const retryDelays = [0,500,1000,2000,4000,8000]" in APP_JS
    assert 'api("/api/catalog", { signal:controller.signal })' in APP_JS
    assert 'api("/api/config/public", { signal:controller.signal })' in APP_JS
    assert 'api("/api/snapshot", { signal:controller.signal })' in APP_JS
    assert "await loadInitialDataWithRetry();" in APP_JS


def test_android_webview_resume_triggers_connection_recovery():
    assert 'document.addEventListener("visibilitychange"' in APP_JS
    assert 'window.addEventListener("pageshow", recover)' in APP_JS
    assert 'window.addEventListener("focus", recover)' in APP_JS
    assert 'window.addEventListener("online", recover)' in APP_JS
    assert "async function recoverAfterAppResume()" in APP_JS
    assert "fetchSnapshot()" in APP_JS


def test_websocket_reconnect_is_single_instance_and_timer_is_tracked():
    assert "state.websocketReconnectTimer" in APP_JS
    assert "current.readyState === WebSocket.OPEN || current.readyState === WebSocket.CONNECTING" in APP_JS
    assert "if (state.websocket !== socket) return;" in APP_JS
    assert "function restartWebSocket()" in APP_JS


def test_frontend_cache_revision_matches_versioned_assets():
    index = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
    worker = (ROOT / "app" / "static" / "service-worker.js").read_text(encoding="utf-8")
    revision = re.search(r'ASSET_VERSION = "gptsol-(\d+)"', worker).group(1)
    assert f"gptsol-{revision}" in index
    assert f'CACHE = "plumbox-gptsol-static-v{revision}"' in worker

