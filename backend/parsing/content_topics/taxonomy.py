"""Declarative content topic taxonomy: what each topic covers and the rules that hint at it.

The rules are hints. With an LLM switched on, the LLM decides an artifact's
topics and the hints are offered to it; with none, the hints are the topics.

This package uses only the standard library and ``parsing``. The API image
ships it with no other dependency, so the topic filter and the ticker topic
view can read the taxonomy.
"""

from __future__ import annotations

from dataclasses import dataclass

# Recorded with every rules-decided topic. A change to the rules or the
# weights below needs a new version, so ``tools.tag_content_topics`` tags the
# stored artifacts again.
RULES_VERSION = "content-topics-rules-v1"


@dataclass(frozen=True)
class TopicRule:
    """A named phrase, matched case-insensitively as whole words.

    ``token`` matches the phrase exactly, for acronyms such as ``ASIC``.
    """

    name: str
    phrase: str
    token: bool = False


@dataclass(frozen=True, kw_only=True)
class TopicDefinition:
    """One stable content topic.

    ``identifier`` is stored and must not change. ``description`` is what the
    LLM prompt says the topic covers. ``category_hints`` are the
    classification categories whose announcements are about this topic, and
    ``category_weight`` how strongly such a category alone suggests it.
    """

    identifier: str
    label: str
    description: str
    title_phrases: tuple[TopicRule, ...] = ()
    body_phrases: tuple[TopicRule, ...] = ()
    negative_phrases: tuple[TopicRule, ...] = ()
    category_hints: tuple[str, ...] = ()
    category_weight: float = 0.0


TOPICS: tuple[TopicDefinition, ...] = (
    TopicDefinition(
        identifier="earnings_guidance",
        label="Earnings and guidance",
        description=(
            "Reported financial results, profit, revenue, margins, earnings per share, "
            "and any guidance or outlook the company gives, confirms, upgrades or "
            "downgrades, including production and cost guidance."
        ),
        title_phrases=(
            TopicRule("results", "results"),
            TopicRule("earnings", "earnings"),
            TopicRule("guidance", "guidance"),
            TopicRule("outlook", "outlook"),
            TopicRule("profit", "profit"),
            TopicRule("trading_update", "trading update"),
            TopicRule("quarterly_report", "quarterly report"),
            TopicRule("quarterly_activities", "quarterly activities"),
            TopicRule("production_report", "production report"),
        ),
        body_phrases=(
            TopicRule("net_profit_after_tax", "net profit after tax"),
            TopicRule("npat", "NPAT", token=True),
            TopicRule("ebitda", "EBITDA", token=True),
            TopicRule("earnings_per_share", "earnings per share"),
            TopicRule("underlying_profit", "underlying profit"),
            TopicRule("statutory_profit", "statutory profit"),
            TopicRule("revenue", "revenue"),
            TopicRule("operating_margin", "operating margin"),
            TopicRule("guidance", "guidance"),
            TopicRule("outlook", "outlook"),
            TopicRule("full_year_result", "full year result"),
            TopicRule("half_year_result", "half year result"),
            TopicRule("reaffirms", "reaffirms"),
            TopicRule("downgrade", "downgrade"),
            TopicRule("upgrade", "upgraded"),
        ),
        negative_phrases=(
            TopicRule("meeting_results", "results of meeting"),
            TopicRule("voting_results", "voting results"),
            TopicRule("poll_results", "results of the poll"),
        ),
        category_hints=(
            "half_year_results",
            "full_year_results",
            "quarterly_trading_update",
            "guidance_update",
            "annual_report",
        ),
        category_weight=0.6,
    ),
    TopicDefinition(
        identifier="litigation",
        label="Litigation",
        description=(
            "Court cases and legal disputes involving the company: class actions, "
            "lawsuits, claims against or by the company, judgments, appeals, "
            "injunctions and legal settlements."
        ),
        title_phrases=(
            TopicRule("class_action", "class action"),
            TopicRule("litigation", "litigation"),
            TopicRule("lawsuit", "lawsuit"),
            TopicRule("legal_proceedings", "legal proceedings"),
            TopicRule("court_proceedings", "court proceedings"),
            TopicRule("judgment", "judgment"),
        ),
        body_phrases=(
            TopicRule("class_action", "class action"),
            TopicRule("litigation", "litigation"),
            TopicRule("lawsuit", "lawsuit"),
            TopicRule("legal_proceedings", "legal proceedings"),
            TopicRule("court_proceedings", "court proceedings"),
            TopicRule("federal_court", "Federal Court"),
            TopicRule("supreme_court", "Supreme Court"),
            TopicRule("high_court", "High Court"),
            TopicRule("plaintiff", "plaintiff"),
            TopicRule("defendant", "defendant"),
            TopicRule("statement_of_claim", "statement of claim"),
            TopicRule("injunction", "injunction"),
            TopicRule("appeal", "appeal"),
            TopicRule("damages", "damages"),
            TopicRule("settle_proceedings", "settle the proceedings"),
        ),
        category_hints=("regulatory_legal",),
        category_weight=0.3,
    ),
    TopicDefinition(
        identifier="regulation",
        label="Regulation",
        description=(
            "Regulators, government policy and approvals that affect the company: "
            "investigations or penalties by ASIC, ACCC, APRA, AUSTRAC and others, "
            "regulatory or competition approvals, licences, new legislation, taxes "
            "or royalties."
        ),
        title_phrases=(
            TopicRule("regulatory", "regulatory"),
            TopicRule("regulator", "regulator"),
            TopicRule("asic", "ASIC", token=True),
            TopicRule("accc", "ACCC", token=True),
            TopicRule("apra", "APRA", token=True),
            TopicRule("austrac", "AUSTRAC", token=True),
            TopicRule("firb", "FIRB", token=True),
            TopicRule("approval", "approval"),
        ),
        body_phrases=(
            TopicRule("asic", "ASIC", token=True),
            TopicRule("accc", "ACCC", token=True),
            TopicRule("apra", "APRA", token=True),
            TopicRule("austrac", "AUSTRAC", token=True),
            TopicRule("firb", "Foreign Investment Review Board"),
            TopicRule("regulator", "regulator"),
            TopicRule("regulatory_approval", "regulatory approval"),
            TopicRule("regulatory_investigation", "regulatory investigation"),
            TopicRule("civil_penalty", "civil penalty"),
            TopicRule("penalty", "penalty"),
            TopicRule("enforceable_undertaking", "enforceable undertaking"),
            TopicRule("infringement_notice", "infringement notice"),
            TopicRule("legislation", "legislation"),
            TopicRule("royalty_regime", "royalty"),
            TopicRule("government_policy", "government policy"),
            TopicRule("compliance", "compliance"),
            TopicRule("tga", "TGA", token=True),
            TopicRule("fda", "FDA", token=True),
        ),
        category_hints=("regulatory_legal",),
        category_weight=0.3,
    ),
    TopicDefinition(
        identifier="product_launch",
        label="Product launches",
        description=(
            "New products, services, projects or assets the company launches, "
            "releases, commercialises or brings into first production, such as a new "
            "drug, device, store format, digital service or a mine's first output."
        ),
        title_phrases=(
            TopicRule("launch", "launch"),
            TopicRule("launches", "launches"),
            TopicRule("unveils", "unveils"),
            TopicRule("new_product", "new product"),
            TopicRule("first_production", "first production"),
            TopicRule("commercial_release", "commercial release"),
            TopicRule("rollout", "rollout"),
        ),
        body_phrases=(
            TopicRule("launch", "launch"),
            TopicRule("launched", "launched"),
            TopicRule("launches", "launches"),
            TopicRule("new_product", "new product"),
            TopicRule("new_service", "new service"),
            TopicRule("unveiled", "unveiled"),
            TopicRule("rollout", "rollout"),
            TopicRule("roll_out", "roll out"),
            TopicRule("commercialisation", "commercialisation"),
            TopicRule("commercial_release", "commercial release"),
            TopicRule("first_production", "first production"),
            TopicRule("first_ore", "first ore"),
            TopicRule("first_cargo", "first cargo"),
            TopicRule("available_to_customers", "available to customers"),
        ),
    ),
    TopicDefinition(
        identifier="macro_exposure",
        label="Macro-economic exposure",
        description=(
            "How economy-wide conditions affect the company: interest rates, "
            "inflation, exchange rates, commodity prices, consumer demand, tariffs, "
            "trade, sanctions, conflict, and China or global growth."
        ),
        title_phrases=(
            TopicRule("interest_rates", "interest rates"),
            TopicRule("inflation", "inflation"),
            TopicRule("tariffs", "tariffs"),
            TopicRule("recession", "recession"),
            TopicRule("commodity_prices", "commodity prices"),
            TopicRule("macroeconomic", "macroeconomic"),
        ),
        body_phrases=(
            TopicRule("interest_rates", "interest rates"),
            TopicRule("cash_rate", "cash rate"),
            TopicRule("reserve_bank", "Reserve Bank"),
            TopicRule("rba", "RBA", token=True),
            TopicRule("inflation", "inflation"),
            TopicRule("exchange_rate", "exchange rate"),
            TopicRule("australian_dollar", "Australian dollar"),
            TopicRule("commodity_prices", "commodity prices"),
            TopicRule("iron_ore_price", "iron ore price"),
            TopicRule("oil_price", "oil price"),
            TopicRule("copper_price", "copper price"),
            TopicRule("tariffs", "tariffs"),
            TopicRule("recession", "recession"),
            TopicRule("economic_slowdown", "economic slowdown"),
            TopicRule("geopolitical", "geopolitical"),
            TopicRule("sanctions", "sanctions"),
            TopicRule("cost_of_living", "cost of living"),
            TopicRule("consumer_demand", "consumer demand"),
            TopicRule("china_demand", "Chinese demand"),
            TopicRule("macroeconomic", "macroeconomic"),
        ),
    ),
)

TOPIC_IDENTIFIERS: tuple[str, ...] = tuple(topic.identifier for topic in TOPICS)
_DEFINITIONS = {topic.identifier: topic for topic in TOPICS}


def topic_definition(identifier: str | None) -> TopicDefinition | None:
    """The definition of a stored topic identifier, if there is one."""
    return _DEFINITIONS.get(identifier) if identifier else None


def topic_label(identifier: str) -> str:
    """A topic's display label, or its identifier's words for an unknown one."""
    definition = _DEFINITIONS.get(identifier)
    return definition.label if definition else identifier.replace("_", " ").capitalize()
