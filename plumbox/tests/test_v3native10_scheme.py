from pathlib import Path


STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def test_installation_scheme_is_registered_as_a_native_view():
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    script = (STATIC / "app.js").read_text(encoding="utf-8")

    assert 'data-view="installation"' not in index
    assert 'data-view="overview"' in index
    assert 'scheme.css?v=gptsol-79' in index
    assert 'app.js?v=gptsol-79' in index
    assert 'installation: "SCHEMAT INSTALACJI"' in script
    assert "installationSchemeHtml" in script
    assert "UKŁAD DEKLAROWANY" not in script
    assert "nie jest pomiarem przepływu" in script


def test_scheme_uses_controller_snapshot_instead_of_demo_modes():
    script = (STATIC / "app.js").read_text(encoding="utf-8")

    for controller_value in (
        "state_label",
        "heating_pump",
        "water_heater_pump",
        "feeder",
        "mixers",
    ):
        assert controller_value in script

    assert 'const feederTemp = finiteNumber(val("feeder_temp", null));' in script
    assert 'Temp. podajnika <b>${escapeHtml(fmt(feederTemp))}°C</b>' in script
    assert 'PODAJNIK <strong>${escapeHtml(fmt(feederTemp))}°C</strong>' not in script
    assert '<b>MIX</b>' not in script
    assert 'assets/mixer-valve.svg' in script
    assert 'assets/valve-atv.svg' in script
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




def test_hydraulic_valve_images_are_served_as_local_svg(client):
    import xml.etree.ElementTree as ET

    for name in ("valve-atv.svg", "mixer-valve.svg"):
        response = client.get(f"/assets/{name}")
        assert response.status_code == 200
        assert "image/svg+xml" in response.headers["content-type"]
        svg = ET.fromstring(response.text)
        assert svg.attrib["viewBox"] == "0 0 64 64"
        assert not svg.findall(".//{http://www.w3.org/2000/svg}script")
