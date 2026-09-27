"""seed the supported ASX tickers

Revision ID: 86d9seedtickers
Revises: 86d8promptversion
Create Date: 2026-09-27

Read routes such as /tickers/symbol/{symbol}/news-feed, /sentiment/{symbol}
and the public-discussion status route return 404 until the ticker row
exists. Only some other routes created the rows on demand, so a fresh
database answered 404 depending on which route happened to run first. The
API Lambda runs with ``lifespan="off"``, so seeding belongs in a migration.

The rows are a snapshot of the supported tickers at this revision; adding a
ticker later needs its own data migration. Existing rows keep curated
values and only gain missing ones, matching ``_ensure_default_tickers``.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "86d9seedtickers"
down_revision: Union[str, None] = "86d8promptversion"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SUPPORTED_TICKERS = (
    ("ANZ", "ANZ Group Holdings Limited", "Financials", "Banks"),
    ("BHP", "BHP Group Limited", "Materials", "Diversified Metals & Mining"),
    ("CBA", "Commonwealth Bank of Australia", "Financials", "Banks"),
    ("COH", "Cochlear Limited", "Health Care", "Health Care Equipment & Supplies"),
    ("COL", "Coles Group Limited", "Consumer Staples", "Food & Staples Retailing"),
    ("CSL", "CSL Limited", "Health Care", "Biotechnology"),
    ("MQG", "Macquarie Group Limited", "Financials", "Capital Markets"),
    ("ORG", "Origin Energy Limited", "Energy", "Oil, Gas & Consumable Fuels"),
    ("RIO", "Rio Tinto Limited", "Materials", "Diversified Metals & Mining"),
    ("TCL", "Transurban Group", "Industrials", "Highways & Railtracks"),
    ("TLS", "Telstra Group Limited", "Communication Services", "Diversified Telecommunication Services"),
    ("WDS", "Woodside Energy Group Limited", "Energy", "Oil, Gas & Consumable Fuels"),
    ("WES", "Wesfarmers Limited", "Consumer Discretionary", "Consumer Staples Distribution & Retail"),
)

SEED_TICKER = sa.text(
    """
    INSERT INTO tickers (id, symbol, company_name, exchange, sector, industry)
    VALUES (gen_random_uuid(), :symbol, :company_name, 'ASX', :sector, :industry)
    ON CONFLICT (symbol) DO UPDATE SET
        company_name = CASE
            WHEN tickers.company_name IS NULL
                OR tickers.company_name = ''
                OR tickers.company_name = tickers.symbol
            THEN EXCLUDED.company_name
            ELSE tickers.company_name
        END,
        exchange = COALESCE(NULLIF(tickers.exchange, ''), EXCLUDED.exchange),
        sector = COALESCE(NULLIF(tickers.sector, ''), EXCLUDED.sector),
        industry = COALESCE(NULLIF(tickers.industry, ''), EXCLUDED.industry)
    """
)


def seed_supported_tickers(bind) -> None:
    for symbol, company_name, sector, industry in SUPPORTED_TICKERS:
        bind.execute(
            SEED_TICKER,
            {
                "symbol": symbol,
                "company_name": company_name,
                "sector": sector,
                "industry": industry,
            },
        )


def upgrade() -> None:
    seed_supported_tickers(op.get_bind())


def downgrade() -> None:
    # Keep the rows: runs, artifacts and watchlists reference them.
    pass
