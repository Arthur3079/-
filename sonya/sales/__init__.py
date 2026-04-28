"""Sales engine: catalog import, recommendation, invoice request, delivery audit.

`sales/catalog_importer.py` parses `knowledge/content_catalog.md` into the
`content_sets` table. `sales/recommend.py` picks the best content set for a
fan given their type / current intent. `sales/engine.py` is the high-level
API the dialogue layer talks to: "should I offer right now? if so, with what
copy?" plus "create an invoice" via the payment_bot bridge.
"""

from sonya.sales.catalog_importer import (
    CatalogEntry,
    import_catalog_file,
    parse_catalog,
    upsert_entry,
)
from sonya.sales.engine import RecommendOutcome, build_recommendation, register_invoice_request
from sonya.sales.recommend import recommend_for_fan

__all__ = [
    "CatalogEntry",
    "RecommendOutcome",
    "build_recommendation",
    "import_catalog_file",
    "parse_catalog",
    "recommend_for_fan",
    "register_invoice_request",
    "upsert_entry",
]
