"""Polskie nazwy, sekcje i przeliczenia dla ecoMAX 860P4-PE."""

from __future__ import annotations

from typing import Any


STATE_LABELS = {
    0: "Wyłączony",
    1: "Stabilizacja",
    2: "Rozpalanie",
    3: "Praca",
    4: "Nadzór",
    5: "Postój",
    6: "Czuwanie",
    7: "Wygaszanie",
    8: "Alarm",
    9: "Ręczny",
    10: "Rozszczelnianie",
    11: "Inny",
}

# Korekta nazwy według porównania użytkownika z ecoNET i wyświetlaczem
# ecoMAX860P4-PE (2026-10-14): podczas startu, przed rozpalaniem,
# faza opisywana dotąd w PlumBox jako „Test płomienia” jest „Czyszczeniem”.
# Dotyczy wyłącznie profilu modelowego; ogólne znaczenie kodu 6 pozostaje bez zmian.
ECOMAX860P4_STATE_LABELS = {
    6: "Czyszczenie",
}

ALERT_LABELS = {
    0: "Zanik zasilania",
    1: "Uszkodzenie czujnika temperatury kotła",
    2: "Przekroczona maksymalna temperatura kotła",
    3: "Uszkodzenie czujnika temperatury podajnika",
    4: "Przekroczona maksymalna temperatura podajnika",
    5: "Uszkodzenie czujnika spalin",
    6: "Przekroczona maksymalna temperatura spalin",
    7: "Nieudane rozpalanie",
    8: "Brak paliwa",
    11: "Awaria wentylatora",
    13: "Nieudane wygaszanie",
    14: "Awaria czujnika płomienia",
    16: "Nieprawidłowe parametry",
    18: "Zadziałał STB kotła",
    19: "Zadziałał STB podajnika",
    22: "Zablokowany podajnik",
    23: "Zanik płomienia",
    24: "Awaria wentylatora wyciągowego",
    32: "Uszkodzenie czujnika CWU",
    38: "Chłodzenie kotła",
    39: "Brak komunikacji z ecoLAMBDA",
    # Kody 44 i 52 wg pyplumio (AlertType): MODULE_B_CONNECTION_FAILURE
    # i FEEDER_CONTROL_FAILURE. Wcześniejsze etykiety („awaria napędu czyszczenia",
    # „zablokowany podajnik") myliły diagnozę — zablokowany podajnik to kod 22.
    44: "Brak komunikacji z modułem B",
    52: "Awaria sterowania podajnikiem",
    255: "Nieznany alarm",
}

SENSOR_META: dict[str, dict[str, Any]] = {
    "heating_temp": {"label": "Kocioł", "unit": "°C", "icon": "boiler"},
    "return_temp": {"label": "Powrót", "unit": "°C", "icon": "return"},
    "water_heater_temp": {"label": "CWU", "unit": "°C", "icon": "water"},
    "feeder_temp": {"label": "Podajnik", "unit": "°C", "icon": "feeder"},
    # PyPlumIO udostępnia to pole w grupie temperatur, ale bez dokumentacji
    # konkretnego czujnika nie przypisujemy mu umownej skali ani znaczenia płomienia.
    "optical_temp": {"label": "Czujnik optyczny", "unit": None, "icon": "sensor"},
    "heating_target": {"label": "Zadana kotła", "unit": "°C", "icon": "target"},
    "water_heater_target": {"label": "Zadana CWU", "unit": "°C", "icon": "target"},
    "boiler_power": {"label": "Moc kotła", "unit": "kW", "icon": "power"},
    "boiler_load": {"label": "Obciążenie", "unit": "%", "icon": "gauge"},
    "fan_power": {"label": "Wentylator", "unit": "%", "icon": "fan"},
    "fuel_level": {"label": "Poziom paliwa", "unit": "%", "icon": "fuel"},
    "fuel_consumption": {"label": "Spalanie", "unit": "kg/h", "icon": "fuel"},
    "fuel_burned": {"label": "Spalone paliwo", "unit": "kg", "icon": "fuel"},
}

SECTIONS = [
    {"id": "heating", "label": "CO i kocioł", "icon": "🔥"},
    {"id": "water_heater", "label": "CWU", "icon": "💧"},
    {"id": "summer", "label": "Lato / zima", "icon": "☀️"},
    {"id": "mixer", "label": "Mieszacz", "icon": "🔀"},
    {"id": "power", "label": "Moc i paliwo", "icon": "⚡"},
    {"id": "kindling", "label": "Rozpalanie", "icon": "✨"},
    {"id": "supervision", "label": "Nadzór", "icon": "👁️"},
    {"id": "burning_off", "label": "Wygaszanie", "icon": "🌘"},
    {"id": "cleaning", "label": "Czyszczenie", "icon": "🧹"},
    {"id": "protections", "label": "Zabezpieczenia", "icon": "🛡️"},
]

# risk:
# safe      — zwykłe ustawienia użytkowe
# advanced  — ustawienia procesu spalania
# critical  — progi bezpieczeństwa

# Klasyfikacja widoku zgodna z ekranami "Parametry użytkownika" i
# "Parametry serwisowe" ecoNET. Jest niezależna od pola ``risk``: zielona
# etykieta użytkowa nie może omijać potwierdzenia zapisu advanced/critical.
ECONET_USER_PARAMETER_NAMES = {
    "ecomax_control",
    "heating_target_temp",
    "fuzzy_logic",
    "thermostat_mode",
    "h2_hysteresis",
    "h1_hysteresis",
    "heating_hysteresis",
    "boiler_power_100",
    "boiler_power_50",
    "boiler_power_30",
    "airflow_correction_30",
    "airflow_correction_50",
    "airflow_correction_100",
    "water_heater_target_temp",
    "water_heater_work_mode",
    "water_heater_hysteresis",
    "water_heater_disinfection",
    "mixer_target_temp:mixer",
    "heating_curve:mixer",
    "heating_curve_shift:mixer",
    "thermostat_mode:mixer",
    "thermostat_decrease_target_temp:mixer",
    "summer_mode",
    "summer_mode_enable_temp",
    "summer_mode_disable_temp",
}

PARAMETER_META: dict[str, dict[str, Any]] = {
    # Kocioł i CO.
    "ecomax_control": {
        "label": "Stan kotła",
        "section": "heating",
        "risk": "safe",
        "kind": "switch",
        "on_label": "Kocioł uruchomiony",
        "off_label": "Kocioł zatrzymany",
        "on_action_label": "Uruchom kocioł",
        "off_action_label": "Zatrzymaj kocioł",
    },
    "heating_target_temp": {
        "label": "Temperatura zadana kotła",
        "section": "heating",
        "risk": "safe",
    },
    "min_heating_target_temp": {
        "label": "Minimalna temperatura zadana kotła",
        "section": "heating",
        "risk": "advanced",
    },
    "max_heating_target_temp": {
        "label": "Maksymalna temperatura zadana kotła",
        "section": "heating",
        "risk": "advanced",
    },
    "heating_pump_enable_temp": {
        "label": "Temperatura załączenia pompy kotła",
        "section": "heating",
        "risk": "safe",
    },
    "heating_hysteresis": {
        "label": "Histereza pracy kotła",
        "section": "power",
        "risk": "advanced",
    },
    "fuzzy_logic": {
        "label": "Tryb pracy kotła",
        "section": "heating",
        "risk": "safe",
        "kind": "switch",
        "on_label": "Fuzzy Logic",
        "off_label": "Zwykły",
        "on_action_label": "Włącz Fuzzy Logic",
        "off_action_label": "Ustaw tryb zwykły",
    },
    "thermostat_mode": {
        "label": "Wybór termostatu kotła",
        "section": "heating",
        "risk": "safe",
        "kind": "switch",
        "on_label": "Włączony",
        "off_label": "Wyłączony",
    },
    "disable_pump_on_thermostat": {
        "label": "Wyłączenie pompy kotła od termostatu",
        "section": "heating",
        "risk": "advanced",
        "kind": "switch",
        "on_label": "Włączony",
        "off_label": "Wyłączony",
    },

    # CWU.
    "water_heater_target_temp": {
        "label": "Temperatura zadana zasobnika CWU",
        "section": "water_heater",
        "risk": "safe",
    },
    "min_water_heater_target_temp": {
        "label": "Minimalna temperatura zadana zasobnika CWU",
        "section": "water_heater",
        "risk": "advanced",
    },
    "max_water_heater_target_temp": {
        "label": "Maksymalna temperatura zadana zasobnika CWU",
        "section": "water_heater",
        "risk": "advanced",
    },
    "water_heater_work_mode": {
        "label": "Tryb pracy pompy CWU",
        "section": "water_heater",
        "risk": "safe",
        "kind": "select",
        "options": {
            "0": "Wyłączony",
            "1": "Praca z priorytetem",
            "2": "Praca bez priorytetu",
        },
    },
    "water_heater_hysteresis": {
        "label": "Histereza zasobnika CWU",
        "section": "water_heater",
        "risk": "safe",
    },
    "water_heater_disinfection": {
        "label": "Dezynfekcja zbiornika CWU",
        "section": "water_heater",
        "risk": "advanced",
        "kind": "switch",
        "on_label": "Włączony",
        "off_label": "Wyłączony",
    },
    "pause_heating_for_water_heater": {
        "label": "Czas postoju pompy kotła od CWU",
        "section": "heating",
        "risk": "advanced",
        "unit": "min",
    },
    "increase_heating_temp_for_water_heater": {
        "label": "Podwyższenie temperatury zadanej kotła od CWU, mieszaczy lub bufora",
        "section": "heating",
        "risk": "advanced",
        "unit": "°C",
    },
    "water_heater_work_extension": {
        "label": "Czas wydłużenia ładowania zasobnika CWU",
        "section": "water_heater",
        "risk": "safe",
        "unit": "min",
    },

    # Lato.
    "summer_mode": {
        "label": "Tryb pracy: Lato / Zima / Auto",
        "section": "summer",
        "risk": "safe",
        "kind": "select",
        "options": {"0": "Zima", "1": "Lato", "2": "Auto"},
    },
    "summer_mode_enable_temp": {
        "label": "Temperatura wejścia w tryb LATO",
        "section": "summer",
        "risk": "safe",
    },
    "summer_mode_disable_temp": {
        "label": "Temperatura wyjścia z trybu LATO",
        "section": "summer",
        "risk": "safe",
    },

    # Moc i paliwo.
    "boiler_power_100": {
        "label": "Moc kotła w kW dla pracy na poziomie 100%",
        "section": "power",
        "risk": "advanced",
    },
    "boiler_power_50": {
        "label": "Moc kotła w kW dla pracy na poziomie 50%",
        "section": "power",
        "risk": "advanced",
    },
    "boiler_power_30": {
        "label": "Moc kotła w kW dla pracy na poziomie 30%",
        "section": "power",
        "risk": "advanced",
    },
    "h2_hysteresis": {
        "label": "Histereza H2 pracy kotła",
        "section": "power",
        "risk": "advanced",
    },
    "h1_hysteresis": {
        "label": "Histereza H1 pracy kotła",
        "section": "power",
        "risk": "advanced",
    },
    "max_fuel_flow": {
        "label": "Szybkość podawania paliwa przez podajnik",
        "section": "power",
        "risk": "advanced",
    },
    "fuel_calorific_value": {
        "label": "Kaloryczność paliwa",
        "section": "power",
        "risk": "advanced",
    },
    "min_fan_power": {
        "label": "Minimalna moc nadmuchu jaką może ustawić użytkownik",
        "section": "power",
        "risk": "advanced",
        "unit": "%",
    },
    "airflow_correction_100": {
        "label": "Korekta mocy nadmuchu przy 100% mocy kotła",
        "section": "power",
        "risk": "advanced",
    },
    "airflow_correction_50": {
        "label": "Korekta mocy nadmuchu przy 50% mocy kotła",
        "section": "power",
        "risk": "advanced",
    },
    "airflow_correction_30": {
        "label": "Korekta mocy nadmuchu przy 30% mocy kotła",
        "section": "power",
        "risk": "advanced",
    },

    # Rozpalanie.
    "kindling_airflow_power": {
        "label": "Moc nadmuchu w trybie rozpalanie",
        "section": "kindling",
        "risk": "advanced",
        "unit": "obr/min",
    },
    "kindling_airflow_delay": {
        "label": "Czas przedmuchu przed rozpalaniem",
        "section": "kindling",
        "risk": "advanced",
        "unit": "s",
    },
    "kindling_test_time": {
        "label": "Czas testu zapłonu",
        "section": "kindling",
        "risk": "advanced",
        "unit": "s",
    },
    "kindling_time": {
        "label": "Czas pracy grzałki w rozpalaniu",
        "section": "kindling",
        "risk": "advanced",
        "unit": "min",
    },
    "warming_up_time": {
        "label": "Czas rozgrzewania grzałki przed rozpalaniem",
        "section": "kindling",
        "risk": "advanced",
        "unit": "s",
    },
    "kindling_finish_threshold_temp": {
        "label": "Próg detekcji płomienia przy czujniku optycznym",
        "section": "kindling",
        "risk": "advanced",
        "unit": "%",
    },
    "kindling_min_power_time": {
        "label": "Czas stabilizacji",
        "section": "kindling",
        "risk": "advanced",
        "unit": "min",
    },
    "stabilization_time": {
        "label": "Czas nadmuchu po rozpaleniu",
        "section": "kindling",
        "risk": "advanced",
        "unit": "s",
    },
    "stabilization_airflow_power": {
        "label": "Nadmuch po rozpaleniu",
        "section": "kindling",
        "risk": "advanced",
        "unit": "obr/min",
    },

    # Nadzór.
    "supervision_time": {
        "label": "Czas nadzoru",
        "section": "supervision",
        "risk": "advanced",
        "unit": "min",
    },
    "fuel_detection_time": {
        "label": "Czas detekcji braku paliwa",
        "section": "power",
        "risk": "advanced",
        "unit": "min",
    },

    # Wygaszanie.
    "burning_off_max_time": {
        "label": "Maksymalny czas wygaszania kotła",
        "section": "burning_off",
        "risk": "advanced",
        "unit": "min",
    },
    "burning_off_min_time": {
        "label": "Minimalny czas po jakim kocioł kończy wygaszanie",
        "section": "burning_off",
        "risk": "advanced",
        "unit": "min",
    },
    "burning_off_airflow_power": {
        "label": "Moc nadmuchu wygaszanie",
        "section": "burning_off",
        "risk": "advanced",
        "unit": "obr/min",
    },
    "burning_off_fan_work": {
        "label": "Czas pracy nadmuchu w wygaszaniu",
        "section": "burning_off",
        "risk": "advanced",
        "unit": "s",
    },
    "burning_off_fan_pause": {
        "label": "Przerwa nadmuchu w wygaszaniu",
        "section": "burning_off",
        "risk": "advanced",
        "unit": "s",
    },
    "start_burning_off": {
        "label": "Próg detekcji płomienia rozpoczynający przedmuch wygaszania",
        "section": "burning_off",
        "risk": "advanced",
        "unit": "%",
    },
    "stop_burning_off": {
        "label": "Próg detekcji płomienia kończący przedmuch wygaszania",
        "section": "burning_off",
        "risk": "advanced",
        "unit": "%",
    },

    # Czyszczenie.
    "cleaning_begin_time": {
        "label": "Czas czyszczenia w trybie rozpalanie",
        "section": "cleaning",
        "risk": "advanced",
        "unit": "s",
    },
    "burning_off_cleaning_time": {
        "label": "Czas czyszczenia w wygaszaniu",
        "section": "cleaning",
        "risk": "advanced",
        "unit": "min",
    },
    "cleaning_airflow_power": {
        "label": "Moc nadmuchu w trybie czyszczenia",
        "section": "cleaning",
        "risk": "advanced",
        "unit": "obr/min",
    },
    "warming_up_pause_time": {
        "label": "Czas pracy do automatycznego czyszczenia kotła",
        "section": "cleaning",
        "risk": "advanced",
        "unit": "godz.",
    },

    # Zabezpieczenia.
    "boiler_alert_temp": {
        "label": "Temperatura alarmu przegrzania kotła",
        "section": "protections",
        "risk": "critical",
    },
    "max_feeder_temp": {
        "label": "Maksymalna temperatura podajnika",
        "section": "protections",
        "risk": "critical",
    },
    "external_boiler_temp": {
        "label": "Temperatura wyłączenia kotła zewnętrznego",
        "section": "protections",
        "risk": "advanced",
        "special_zero": True,
    },

    # Mieszacz.
    "heating_curve:mixer": {
        "label": "Krzywa grzewcza mieszacza",
        "section": "mixer",
        "risk": "safe",
    },
    "heating_curve_shift:mixer": {
        "label": "Przesunięcie krzywej grzewczej mieszacza",
        "section": "mixer",
        "risk": "safe",
    },
    "mixer_target_temp": {
        "label": "Temperatura zadana obiegu grzewczego",
        "section": "mixer",
        "risk": "safe",
    },
    "min_target_temp": {
        "label": "Minimalna temperatura zadana obiegu grzewczego",
        "section": "mixer",
        "risk": "advanced",
    },
    "max_target_temp": {
        "label": "Maksymalna temperatura zadana obiegu grzewczego",
        "section": "mixer",
        "risk": "advanced",
    },
    "thermostat_decrease_target_temp": {
        "label": "Obniżenie temperatury zadanej obiegu przy rozwartym styku termostatu",
        "section": "mixer",
        "risk": "safe",
    },
    "work_mode": {
        "label": "Obsługa mieszacza",
        "section": "mixer",
        "risk": "safe",
        "kind": "select",
        "options": {
            "0": "Wyłączony",
            "1": "CO włączone",
            "2": "Podłogówka",
            "3": "Tylko pompa",
        },
    },
    "mixer_input_dead_zone": {
        "label": "Nieczułość obiegu mieszacza",
        "section": "mixer",
        "risk": "advanced",
    },
    "thermostat_mode:mixer": {
        "label": "Wybór termostatu obiegu",
        "section": "mixer",
        "risk": "safe",
        "kind": "select",
        "options": {"0": "Wyłączony", "1": "Włączony"},
    },
    "disable_pump_on_thermostat:mixer": {
        "label": "Wyłączenie pompy mieszacza od termostatu",
        "section": "mixer",
        "risk": "advanced",
        "kind": "switch",
        "on_label": "Włączony",
        "off_label": "Wyłączony",
    },
}


def meta_for(name: str, scope: str = "ecomax") -> dict[str, Any]:
    scoped_key = f"{name}:mixer" if scope == "mixer" else name
    meta = dict(PARAMETER_META.get(scoped_key, PARAMETER_META.get(name, {})))
    meta.setdefault("label", name.replace("_", " ").capitalize())
    meta.setdefault("section", "other")
    meta.setdefault("risk", "advanced")
    meta.setdefault("access", "user" if scoped_key in ECONET_USER_PARAMETER_NAMES else "service")
    return meta


def model_parameter_range(name: str, scope: str, product_id: Any) -> tuple[int, int] | None:
    """SF 11/130 / 860P4-LZ range confirmed on the user's boiler, 2026-10-25.

    Do not apply this correction to the PE/RPM profile or unidentified models.
    """
    if scope == "ecomax" and name == "summer_mode_disable_temp" and str(product_id) == "2":
        return (1, 15)
    return None


# Przelicznik POTWIERDZONY SPRZĘTOWO (2026-07-17, ecoMAX 860P4 użytkownika):
# korekty nadmuchu są przechowywane natywnie z przesunięciem +100
# (natywne 100 = korekta 0 na panelu kotła, 101 = +1; zakres natywny 80–130
# = panel −20…+30). Innych parametrów nie przeliczamy bez takiego dowodu.
AIRFLOW_CORRECTION_OFFSET = 100
AIRFLOW_CORRECTION_NAMES = {
    "airflow_correction_100",
    "airflow_correction_50",
    "airflow_correction_30",
}

# Przelicznik POTWIERDZONY SPRZĘTOWO (2026-07-18, ecoMAX 860P4-PE,
# product id 211). Sterownik przesyła nastawy wentylatora jako wartość
# kodowaną, natomiast panel kotła i ecoNET pokazują obroty na minutę:
# 115 -> 1450, 95 -> 1250, 130 -> 1600, 180 -> 2100.
FAN_RPM_SCALE = 10
FAN_RPM_OFFSET = 300
FAN_RPM_NAMES = {
    "kindling_airflow_power",
    "stabilization_airflow_power",
    "burning_off_airflow_power",
    "cleaning_airflow_power",
}

FAN_RPM_PRODUCT_IDS = {211}


def fan_rpm_profile_state(profile_mode: str, product_id: Any = None) -> dict[str, Any]:
    """Stan identyfikacji profilu używanego do przeliczania wentylatora.

    Znane, ale obce ID zawsze wygrywa z deklaracją FIXED. Fallback FIXED jest
    dozwolony wyłącznie wtedy, gdy ramka produktu nie dostarczyła żadnego ID.
    """
    mode = str(profile_mode or "").lower()
    parsed_id: int | None = None
    try:
        if product_id not in {None, ""}:
            parsed_id = int(product_id)
    except (TypeError, ValueError):
        parsed_id = None

    if parsed_id in FAN_RPM_PRODUCT_IDS:
        return {
            "enabled": True,
            "status": "verified",
            "source": "product_id",
            "product_id": parsed_id,
            "label": f"Model potwierdzony: product ID {parsed_id}",
            "warning": None,
        }
    if parsed_id is not None:
        return {
            "enabled": False,
            "status": "foreign",
            "source": "product_id",
            "product_id": parsed_id,
            "label": "860P4-LZ" if parsed_id == 2 else f"Inny sterownik: product ID {parsed_id}",
            "warning": (
                f"Przeliczniki modelowe (RPM i korekty nadmuchu) są nieaktywne: "
                f"product ID {parsed_id} nie ma potwierdzonego mapowania. "
                "Pokazywane są wartości natywne sterownika."
            ),
        }
    if mode == "fixed_ecomax860p4":
        return {
            "enabled": True,
            "status": "fixed_fallback",
            "source": "fixed_profile",
            "product_id": None,
            "label": "Model przyjęty z profilu FIXED ecoMAX860P4",
            "warning": (
                "Nie odebrano product ID. Przeliczniki modelowe działają awaryjnie na podstawie "
                "zadeklarowanego profilu FIXED ecoMAX860P4."
            ),
        }
    return {
        "enabled": False,
        "status": "inactive",
        "source": "missing_product_id",
        "product_id": None,
        "label": "Model nierozpoznany — brak product ID",
        "warning": (
            "Przeliczniki modelowe (RPM i korekty nadmuchu) są nieaktywne, ponieważ nie odebrano product ID. "
            "Pokazywane są wartości natywne sterownika."
        ),
    }


def fan_rpm_profile_enabled(profile_mode: str, product_id: Any = None) -> bool:
    """Czy bieżący stan profilu zezwala na potwierdzoną lub jawną skalę RPM."""
    return bool(fan_rpm_profile_state(profile_mode, product_id)["enabled"])


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def display_value(
    name: str,
    native_value: Any,
    scope: str = "ecomax",
    *,
    fan_rpm_enabled: bool = False,
    airflow_correction_enabled: bool = False,
) -> Any:
    """Wartość dla UI; przeliczenia wyłącznie potwierdzone na żywym sterowniku."""
    if airflow_correction_enabled and name in AIRFLOW_CORRECTION_NAMES and _is_number(native_value):
        return native_value - AIRFLOW_CORRECTION_OFFSET
    if fan_rpm_enabled and name in FAN_RPM_NAMES and _is_number(native_value):
        return native_value * FAN_RPM_SCALE + FAN_RPM_OFFSET
    return native_value


def native_value(
    name: str,
    shown_value: Any,
    scope: str = "ecomax",
    *,
    fan_rpm_enabled: bool = False,
    airflow_correction_enabled: bool = False,
) -> Any:
    """Wartość dla PyPlumIO w natywnej skali sterownika."""
    if airflow_correction_enabled and name in AIRFLOW_CORRECTION_NAMES and _is_number(shown_value):
        return shown_value + AIRFLOW_CORRECTION_OFFSET
    if fan_rpm_enabled and name in FAN_RPM_NAMES and _is_number(shown_value):
        native = (shown_value - FAN_RPM_OFFSET) / FAN_RPM_SCALE
        if not float(native).is_integer():
            raise ValueError(
                f"Parametr '{name}' musi być ustawiany co {FAN_RPM_SCALE} obr/min."
            )
        return int(native)
    return shown_value


def display_step(
    name: str,
    native_step: Any,
    scope: str = "ecomax",
    *,
    fan_rpm_enabled: bool = False,
) -> Any:
    """Krok edycji w jednostce prezentowanej przez dashboard."""
    if fan_rpm_enabled and name in FAN_RPM_NAMES and _is_number(native_step):
        return native_step * FAN_RPM_SCALE
    return native_step

