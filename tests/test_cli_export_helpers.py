from scrapyfy.cli import _parse_company_slugs
from scrapyfy.excel_service import ExcelReportService


def test_parse_company_slugs_supports_brackets() -> None:
    assert _parse_company_slugs("[company-uno, company-dos]") == [
        "company-uno",
        "company-dos",
    ]


def test_normalize_sheet_name_replaces_invalid_chars() -> None:
    assert ExcelReportService._normalize_sheet_name("Caja/Arequipa:?*") == "Caja-Arequipa---"
