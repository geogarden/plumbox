from pathlib import Path


STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def test_installation_scheme_is_registered_as_a_native_view():
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    script = (STATIC / "app.js").read_text(encoding="utf-8")

    assert 'data-view="installation"' in index
    assert "Schemat instalacji" in index
    assert 'scheme.css?v=gptsol-44' in index
    assert 'app.js?v=gptsol-44' in index
    assert 'installation: "SCHEMAT INSTALACJI"' in script
    assert "installationSchemeHtml" in script
    assert "UKŁAD DEKLAROWANY" in script
    assert "nie jest pomiarem przepływu" in script


def test_scheme_uses_controller_snapshot_instead_of_demo_modes():
    script = (STATIC / "app.js").read_text(encoding="utf-8")

    for controller_value in (
        "state_label",
        "heating_pump",
        "water_heater_pump",
        "optical_temp",
        "feeder",
        "mixers",
    ):
        assert controller_value in script

    assert 'const feederTemp = finiteNumber(val("feeder_temp", null));' in script
    assert 'PALNIK <strong>${escapeHtml(fmt(feederTemp))}°C</strong>' in script
    assert 'PODAJNIK <strong>${escapeHtml(fmt(feederTemp))}°C</strong>' not in script
    assert '<b>MIX</b>' in script
    assert '<b>×</b>' not in script
    assert "fmt(feederTemp)" in script

    assert "data-mode=" not in script
    assert "Postój · podgląd koncepcyjny" not in script


def test_scheme_styles_are_scoped_and_responsive():
    stylesheet = (STATIC / "scheme.css").read_text(encoding="utf-8")

    assert ".installation-scheme" in stylesheet
    assert ".scheme-plant" in stylesheet
    assert "@media (max-width: 760px)" in stylesheet
    assert "transform: scale(var(--scheme-scale" in stylesheet


def test_live_refresh_preserves_computed_scheme_layout():
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    stylesheet = (STATIC / "scheme.css").read_text(encoding="utf-8")

    assert 'live.classList.contains("scheme-canvas")' in script
    assert 'live.classList.contains("scheme-plant")' in script
    assert "!schemeLayoutStyle" in script
    assert "captureInstallationScroll" in script
    assert "restoreInstallationScroll(scrollPositions)" in script
    assert "overflow-anchor: none" in stylesheet
