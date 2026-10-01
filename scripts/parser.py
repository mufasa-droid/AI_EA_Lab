"""
MT5 Strategy Tester Report Parser entrypoint.
Aliases parse_report.py for backward and cross-script compatibility.
"""
import sys
from pathlib import Path

# Add project root to sys.path if not present
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.parse_report import (
    PARSER_VERSION,
    PARSER_SCHEMA_VERSION,
    MT5ReportHTMLParser,
    parse_report,
    read_report_html,
    extract_report_elements,
    parse_float,
    parse_int,
    parse_percent,
    parse_drawdown,
    parse_count_and_percent,
    parse_consecutive_wins_losses,
    parse_maximal_consecutive_profit_loss,
    parse_value_and_percent,
    main,
)

if __name__ == "__main__":
    main()
