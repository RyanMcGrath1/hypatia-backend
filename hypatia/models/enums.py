"""Shared enums for the Hypatia API.

Prefer enums for closed choice sets (API keys, directions, status labels).
Keep FRED series id / label / unit catalogs in service modules as data, not enums.
"""

from __future__ import annotations

from enum import Enum


class FredObservationParam(str, Enum):
    """Whitelisted query params for FRED ``series/observations`` proxies."""

    SERIES_ID = "series_id"
    REALTIME_START = "realtime_start"
    REALTIME_END = "realtime_end"
    OBSERVATION_START = "observation_start"
    OBSERVATION_END = "observation_end"
    UNITS = "units"
    FREQUENCY = "frequency"
    AGGREGATION_METHOD = "aggregation_method"
    OUTPUT_TYPE = "output_type"
    LIMIT = "limit"
    OFFSET = "offset"
    SORT_ORDER = "sort_order"

    @classmethod
    def values(cls) -> frozenset[str]:
        return frozenset(member.value for member in cls)


class FredSortOrder(str, Enum):
    """FRED ``sort_order`` values used by Hypatia."""

    ASC = "asc"
    DESC = "desc"


class FredUnitsMode(str, Enum):
    """FRED ``units`` modes Hypatia actually requests (not the full FRED catalog)."""

    CHG = "chg"
    PC1 = "pc1"
    PCH = "pch"


class GNewsHeadlineParam(str, Enum):
    """Whitelisted query params forwarded to GNews top-headlines."""

    CATEGORY = "category"
    LANG = "lang"
    COUNTRY = "country"
    NULLABLE = "nullable"
    FROM = "from"
    TO = "to"
    Q = "q"
    TRUNCATE = "truncate"

    @classmethod
    def values(cls) -> frozenset[str]:
        return frozenset(member.value for member in cls)


class EconomySectionKey(str, Enum):
    """Economy dashboard ``sections`` object keys."""

    GDP = "gdp"
    CONSUMER_SPENDING = "consumer_spending"
    LABOR = "labor"
    INTEREST_RATES = "interest_rates"
    INFLATION = "inflation"
    HOUSING = "housing"


class LaborAgeGroup(str, Enum):
    """BLS age cohorts for labor age-metrics responses."""

    AGE_16_19 = "16-19"
    AGE_20_24 = "20-24"
    AGE_25_54 = "25-54"
    AGE_55_PLUS = "55+"


class LaborAgeMetricId(str, Enum):
    """Metric ids in ``GET /api/economy/labor/age-metrics`` payloads."""

    UNEMPLOYMENT_RATE = "unemployment_rate"
    LABOR_FORCE_PARTICIPATION = "labor_force_participation"
    EMPLOYMENT_POPULATION_RATIO = "employment_population_ratio"


class TrendDirection(str, Enum):
    """Directional trend used by dashboard sentiment."""

    UP = "up"
    DOWN = "down"
    FLAT = "flat"


class InflationAcceleration(str, Enum):
    """CPI overview month-over-month acceleration label."""

    FLAT = "flat"
    ACCELERATING = "accelerating"
    DECELERATING = "decelerating"


class SentimentStatus(str, Enum):
    """Composite sentiment status band on the economy dashboard."""

    OPTIMAL = "OPTIMAL"
    STEADY = "STEADY"
    WEAK = "WEAK"


class RiskLevel(str, Enum):
    """GDP growth-headwinds risk levels."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @property
    def label(self) -> str:
        return {
            RiskLevel.HIGH: "High Risk",
            RiskLevel.MEDIUM: "Medium Risk",
            RiskLevel.LOW: "Low Risk",
        }[self]


class GdpSectorKey(str, Enum):
    """Keys in GDP sector-contribution responses."""

    SERVICES = "services"
    MANUFACTURING = "manufacturing"
    AGRICULTURE = "agriculture"


class GdpHeadwindKey(str, Enum):
    """Internal fetch keys for GDP growth-headwinds FRED pulls."""

    SUPPLY_CHAIN = "supply_chain"
    FED_LOWER = "fed_lower"
    FED_UPPER = "fed_upper"
    YIELD_CURVE = "yield_curve"
    INFLATION = "inflation"


class GdpHeadwindCardKey(str, Enum):
    """Public ``key`` values on GDP growth-headwinds response cards."""

    SUPPLY_CHAIN = "supply_chain"
    INTEREST_RATES = "interest_rates"
    YIELD_CURVE = "yield_curve"
    INFLATION = "inflation"


class CpiComponentKey(str, Enum):
    """CPI component breakdown keys (plus headline)."""

    HEADLINE = "headline"
    SHELTER = "shelter"
    FOOD = "food"
    ENERGY = "energy"
    CORE_GOODS = "core_goods"
    CORE_SERVICES = "core_services"


class PceMetricKey(str, Enum):
    """PCE vs Fed-target metric keys."""

    HEADLINE = "headline"
    CORE = "core"


class OpenFecNamesParam(str, Enum):
    """Query params handled by the OpenFEC candidate-names proxy."""

    Q = "q"
    NAME = "name"
    TYPEAHEAD = "typeahead"
    PAGE = "page"
    PER_PAGE = "per_page"

    @classmethod
    def values(cls) -> frozenset[str]:
        return frozenset(member.value for member in cls)
