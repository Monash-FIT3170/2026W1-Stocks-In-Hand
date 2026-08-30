"""Declarative category taxonomy for company and ASX documents."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PatternRule:
    """A named phrase, token or regular-expression rule."""
    name: str
    pattern: str
    token: bool = False
    regex: bool = False


@dataclass(frozen=True)
class CategoryDefinition:
    """All declarative classification evidence for one stable category."""
    identifier: str
    compatibility_category: str
    title_phrases: tuple[PatternRule, ...] = ()
    title_tokens: tuple[PatternRule, ...] = ()
    form_identifiers: tuple[PatternRule, ...] = ()
    body_phrases: tuple[PatternRule, ...] = ()
    negative_phrases: tuple[PatternRule, ...] = ()


TAXONOMY: tuple[CategoryDefinition, ...] = (
    CategoryDefinition(
        identifier="quarterly_trading_update",
        compatibility_category="QuarterlyTradingUpdate",
        title_phrases=(
            PatternRule("quarterly_update", "quarterly update"),
            PatternRule("quarterly_activities_report", "quarterly activities report"),
            PatternRule("quarterly_production_report", "quarterly production report"),
            PatternRule("trading_update", "trading update"),
            PatternRule("sales_update", "sales update"),
        ),
        title_tokens=tuple(
            PatternRule(f"{token.casefold()}_token", token, token=True)
            for token in ("Q1", "Q2", "Q3", "Q4", "1Q", "2Q", "3Q", "4Q")
        ),
        body_phrases=(
            PatternRule("quarterly_period", "for the quarter"),
            PatternRule("quarterly_sales", "quarterly sales"),
            PatternRule("operating_volumes", "operating volumes"),
            PatternRule("production_volumes", "production volumes"),
        ),
    ),
    CategoryDefinition(
        identifier="dividend_announcement",
        compatibility_category="DividendAnnouncement",
        title_phrases=(
            PatternRule("dividend_announcement", "dividend announcement"),
            PatternRule("dividend_distribution", "dividend distribution"),
            PatternRule("dividend_key_dates", "dividend key dates"),
            PatternRule("distribution_announcement", "distribution announcement"),
            PatternRule("interim_dividend", "interim dividend"),
            PatternRule("final_dividend", "final dividend"),
            PatternRule("special_dividend", "special dividend"),
        ),
        form_identifiers=(PatternRule("appendix_3a1", "Appendix 3A.1"),),
        body_phrases=(
            PatternRule("declared_dividend", "declared a dividend"),
            PatternRule("cents_per_share", "cents per share"),
            PatternRule("payment_date", "payment date"),
            PatternRule("record_date", "record date"),
            PatternRule("amount_per_security", "amount per security"),
            PatternRule("special_dividend_body", "special dividend"),
        ),
    ),
    CategoryDefinition(
        identifier="guidance_update",
        compatibility_category="GuidanceUpdate",
        title_phrases=(
            PatternRule("guidance_update", "guidance update"),
            PatternRule("earnings_guidance", "earnings guidance"),
            PatternRule("guidance_upgrade", "guidance upgrade"),
            PatternRule("guidance_withdrawal", "withdrawal of guidance"),
            PatternRule("guidance_reaffirmed", "guidance reaffirmed"),
            PatternRule("updated_outlook", "updated outlook"),
            PatternRule("earnings_forecast", "earnings forecast"),
        ),
        body_phrases=(
            PatternRule("earnings_range", "earnings to be between"),
            PatternRule("revised_guidance", "revised earnings guidance"),
            PatternRule("upgraded_guidance", "guidance has been upgraded"),
            PatternRule("withdrawn_guidance", "withdrawn its previously issued"),
            PatternRule("reaffirms_guidance", "reaffirms full year guidance"),
            PatternRule("forecast_revenue", "forecast revenue"),
        ),
    ),
    CategoryDefinition(
        identifier="half_year_results",
        compatibility_category="HalfYearResults",
        title_phrases=(
            PatternRule("half_year_results", "half year"),
            PatternRule("interim_results", "interim results"),
        ),
        title_tokens=(
            PatternRule("first_half_token", "1H", token=True),
            PatternRule("half_one_token", "H1", token=True),
        ),
        form_identifiers=(PatternRule("appendix_4d", "Appendix 4D"),),
        body_phrases=(
            PatternRule("six_month_period", "six months ended"),
            PatternRule("interim_financial_report", "interim financial report"),
            PatternRule("half_year_report", "half year report"),
            PatternRule("condensed_financial_statements", "condensed financial statements"),
        ),
        negative_phrases=(PatternRule("dividend_conflict", "dividend"),),
    ),
    CategoryDefinition(
        identifier="full_year_results",
        compatibility_category="FullYearResults",
        title_phrases=(
            PatternRule("full_year_results", "full year results"),
            PatternRule("preliminary_final_report", "preliminary final report"),
            PatternRule("year_end_results", "year end financial results"),
        ),
        title_tokens=(
            PatternRule(
                "financial_year_results_token",
                r"(?<![A-Za-z0-9])FY\s*20\d{2}\s+Results(?![A-Za-z0-9])",
                regex=True,
            ),
        ),
        form_identifiers=(PatternRule("appendix_4e", "Appendix 4E"),),
        body_phrases=(
            PatternRule("twelve_month_period", "twelve months ended"),
            PatternRule("preliminary_final_body", "preliminary final report"),
            PatternRule("complete_financial_year", "complete financial year"),
            PatternRule("year_end_net_debt", "year end net debt"),
            PatternRule("audited_results", "audited results"),
        ),
        negative_phrases=(PatternRule("annual_report_conflict", "annual report"),),
    ),
    CategoryDefinition(
        identifier="annual_report",
        compatibility_category="AnnualReport",
        title_phrases=(
            PatternRule("annual_report", "annual report"),
            PatternRule("concise_annual_report", "concise annual report"),
            PatternRule("annual_financial_report", "annual financial report"),
            PatternRule("annual_report_accounts", "annual report and accounts"),
            PatternRule("integrated_annual_report", "integrated annual report"),
        ),
        body_phrases=(
            PatternRule("directors_report", "directors report"),
            PatternRule("remuneration_report", "remuneration report"),
            PatternRule("audited_financial_statements", "audited financial statements"),
            PatternRule("auditors_report", "auditor's report"),
            PatternRule("auditors_opinion", "auditor's opinion"),
            PatternRule("notes_financial_statements", "notes to the financial statements"),
        ),
        negative_phrases=(
            PatternRule("sustainability_report_conflict", "sustainability report"),
            PatternRule("community_report_conflict", "community report"),
        ),
    ),
    CategoryDefinition(
        identifier="security_notification",
        compatibility_category="SecurityNotification",
        title_phrases=(
            PatternRule("issue_securities", "notification of issue of securities"),
            PatternRule("cessation_securities", "notification of cessation of securities"),
            PatternRule("change_number_securities", "change in number of securities"),
        ),
        form_identifiers=(
            PatternRule("appendix_3g", "Appendix 3G"),
            PatternRule("appendix_3h", "Appendix 3H"),
        ),
        body_phrases=(
            PatternRule("unquoted_equity_securities", "unquoted equity securities"),
            PatternRule("securities_ceased", "securities following expiry"),
            PatternRule("securities_on_issue", "securities on issue"),
            PatternRule("issue_ordinary_securities", "issue of ordinary securities"),
        ),
        negative_phrases=(
            PatternRule("trading_halt_conflict", "trading halt"),
            PatternRule("buyback_conflict", "share buy back"),
            PatternRule("entitlement_conflict", "entitlement offer"),
        ),
    ),
    CategoryDefinition(
        identifier="capital_management",
        compatibility_category="CapitalManagement",
        title_phrases=(
            PatternRule("equity_raising", "equity raising"),
            PatternRule("capital_raising", "capital raising"),
            PatternRule("placement", "placement"),
            PatternRule("entitlement_offer", "entitlement offer"),
            PatternRule("share_purchase_plan", "share purchase plan"),
            PatternRule("share_buyback", "share buy back"),
        ),
        body_phrases=(
            PatternRule("institutional_placement", "institutional placement"),
            PatternRule("pro_rata_offer", "pro rata entitlement offer"),
            PatternRule("eligible_shareholders", "eligible shareholders"),
            PatternRule("on_market_buyback", "on market share buy back"),
            PatternRule("issue_new_shares", "issue of new shares"),
        ),
        negative_phrases=(
            PatternRule("security_form_conflict", "Appendix 3G"),
            PatternRule("security_cessation_conflict", "Appendix 3H"),
        ),
    ),
    CategoryDefinition(
        identifier="corporate_action",
        compatibility_category="CorporateAction",
        title_phrases=(
            PatternRule("acquisition", "acquisition"),
            PatternRule("acquire", "acquire"),
            PatternRule("divestment", "divestment"),
            PatternRule("merger", "merger"),
            PatternRule("demerger", "demerger"),
            PatternRule("joint_venture", "joint venture"),
        ),
        body_phrases=(
            PatternRule("binding_acquisition", "binding agreement to acquire"),
            PatternRule("business_disposal", "disposal"),
            PatternRule("scheme_arrangement", "scheme of arrangement"),
            PatternRule("separately_listed", "separately listed company"),
            PatternRule("formed_joint_venture", "formed a joint venture"),
        ),
        negative_phrases=(PatternRule("customer_contract_conflict", "customer contract"),),
    ),
    CategoryDefinition(
        identifier="leadership_change",
        compatibility_category="LeadershipChange",
        title_phrases=(
            PatternRule("chief_executive_appointment", "appointment of chief executive officer"),
            PatternRule("director_resignation", "director resignation"),
            PatternRule("leadership_changes", "leadership changes"),
            PatternRule("board_appointment", "board appointment"),
            PatternRule("management_restructure", "management restructure"),
            PatternRule("ceo_departure", "CEO departure"),
        ),
        body_phrases=(
            PatternRule("appointed_chief_executive", "appointed chief executive officer"),
            PatternRule("resigned_board", "resigned from the board"),
            PatternRule("chief_financial_officer", "chief financial officer"),
            PatternRule("non_executive_director", "non executive director"),
            PatternRule("executive_reporting_lines", "executive reporting lines"),
            PatternRule("departure_chief_executive", "departure of the chief executive officer"),
        ),
    ),
    CategoryDefinition(
        identifier="governance_meeting",
        compatibility_category="GovernanceMeeting",
        title_phrases=(
            PatternRule("notice_agm", "notice of annual general meeting"),
            PatternRule("results_agm", "results of annual general meeting"),
            PatternRule("notice_egm", "notice of extraordinary general meeting"),
            PatternRule("governance_statement", "corporate governance statement"),
            PatternRule("proxy_form", "proxy form"),
            PatternRule("general_meeting", "general meeting"),
            PatternRule("notice_agm_short", "notice of AGM"),
        ),
        body_phrases=(
            PatternRule("annual_general_meeting", "annual general meeting"),
            PatternRule("decided_by_poll", "decided by poll"),
            PatternRule("extraordinary_general_meeting", "extraordinary general meeting"),
            PatternRule("governance_recommendations", "governance recommendations"),
            PatternRule("voting_instructions", "voting instructions"),
            PatternRule("general_meeting_body", "general meeting"),
        ),
    ),
    CategoryDefinition(
        identifier="regulatory_legal",
        compatibility_category="RegulatoryLegal",
        title_phrases=(
            PatternRule("accc_determination", "ACCC determination"),
            PatternRule("litigation_update", "litigation update"),
            PatternRule("regulatory_investigation", "regulatory investigation"),
            PatternRule("regulatory_approval", "regulatory approval"),
            PatternRule("court_proceedings", "court proceedings"),
        ),
        body_phrases=(
            PatternRule("regulator_determination", "regulator determination"),
            PatternRule("federal_court", "Federal Court"),
            PatternRule("formal_investigation", "formal investigation"),
            PatternRule("approval_granted", "approval has been granted"),
            PatternRule("civil_penalties", "civil penalties"),
        ),
        negative_phrases=(PatternRule("price_query_conflict", "price query"),),
    ),
    CategoryDefinition(
        identifier="executive_transcript",
        compatibility_category="ExecutiveTranscript",
        title_phrases=(
            PatternRule("chief_executive_interview", "CEO interview"),
            PatternRule("briefing_transcript", "briefing transcript"),
            PatternRule("earnings_call_transcript", "earnings call transcript"),
            PatternRule("executive_qa", "executive Q&A"),
            PatternRule("bluenotes_interview", "Bluenotes CEO interview"),
            PatternRule("transcript", "transcript"),
            PatternRule("interview", "interview"),
        ),
        body_phrases=(
            PatternRule("interviewer_label", "Interviewer"),
            PatternRule("moderator_label", "Moderator"),
            PatternRule("operator_label", "Operator"),
            PatternRule("question_label", "Question"),
            PatternRule("answer_label", "Answer"),
        ),
    ),
)
