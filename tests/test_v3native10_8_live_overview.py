from pathlib import Path


STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def test_overview_chart_appends_live_websocket_temperature_samples():
    script = (STATIC / "app.js").read_text(encoding="utf-8")

    assert "function appendOverviewTemperatureSample()" in script
    assert "overviewHistoryRevision" in script
    assert "updateSparks();\n        appendOverviewTemperatureSample();" in script
    assert 'String(state.overviewHistoryRevision)' in script


def test_controller_tile_uses_process_phase_but_command_keeps_boolean_value():
    script = (STATIC / "app.js").read_text(encoding="utf-8")

    assert 'parameter.name === "ecomax_control" && value === undefined' in script
    assert 'const controllerPhase = val("state_label", null);' in script
    assert 'data-switch-value="false"' in script
    assert 'data-switch-value="true"' in script
