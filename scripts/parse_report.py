import argparse
import json
import re
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path


PARSER_VERSION = "1.0.0"
PARSER_SCHEMA_VERSION = 1


class MT5ReportHTMLParser(HTMLParser):
    """
    Extract structured table rows and cell contents from an MT5 Strategy Tester HTML report.
    """

    def __init__(self):
        super().__init__()
        self.rows = []
        self.current_row = []
        self.current_cell = []
        self.in_cell = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "tr":
            self.current_row = []
        elif tag in ("td", "th"):
            self.in_cell = True
            self.current_cell = []
        elif tag == "br" and self.in_cell:
            self.current_cell.append(" ")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("td", "th") and self.in_cell:
            text = " ".join("".join(self.current_cell).split())
            self.current_row.append(text)
            self.in_cell = False
        elif tag == "tr":
            if self.current_row:
                self.rows.append(self.current_row)

    def handle_data(self, data):
        if self.in_cell:
            self.current_cell.append(data)


def clean_text(value):
    return re.sub(r"\s+", " ", value).strip()


def normalize_number(value):
    if value is None:
        return ""
    # Remove non-breaking spaces, regular spaces, and standard formatting commas
    return str(value).strip().replace("\xa0", " ").replace(" ", "").replace(",", "")


def parse_float(value):
    if value is None or str(value).strip() == "":
        return None
    cleaned = normalize_number(value)
    # Extract leading float number if present
    match = re.search(r"^-?\d+(?:\.\d+)?", cleaned)
    if match:
        try:
            return float(match.group(0))
        except ValueError:
            return None
    return None


def parse_int(value):
    if value is None or str(value).strip() == "":
        return None
    cleaned = normalize_number(value)
    match = re.search(r"^-?\d+", cleaned)
    if match:
        try:
            return int(match.group(0))
        except ValueError:
            return None
    return None


def parse_percent(value):
    if not value:
        return None
    match = re.search(r"(-?\d+(?:[.,]\d+)?)\s*%", str(value))
    return float(match.group(1).replace(",", ".")) if match else None


def parse_drawdown(raw):
    """
    Parses drawdown string which may be:
    - '0.00 (0.00%)' (value and percent)
    - '0.00% (0.00)' (percent and value)
    - '0.00' (value only)
    """
    if raw is None or not str(raw).strip():
        return {"value": None, "percent": None, "raw": raw}

    raw_str = str(raw).strip()
    pct = parse_percent(raw_str)

    # Remove the percent portion and parentheses to isolate the absolute amount
    amount_str = re.sub(r"\(?\s*-?\d+(?:[.,]\d+)?\s*%\s*\)?", "", raw_str).strip().strip("()")
    val = parse_float(amount_str) if amount_str else None

    return {
        "value": val,
        "percent": pct,
        "raw": raw_str,
    }


def parse_count_and_percent(raw):
    """
    Parses trade count & percentage string such as:
    - '0 (0.00%)'
    - '12 (60.00%)'
    """
    if raw is None or not str(raw).strip():
        return {"count": None, "percent": None, "raw": raw}

    raw_str = str(raw).strip()
    match = re.search(r"(-?\d+)\s*\(\s*(-?\d+(?:[.,]\d+)?)\s*%\s*\)", raw_str)
    if match:
        return {
            "count": int(match.group(1)),
            "percent": float(match.group(2).replace(",", ".")),
            "raw": raw_str,
        }

    c = parse_int(raw_str)
    return {"count": c, "percent": None, "raw": raw_str}


def parse_consecutive_wins_losses(raw):
    """
    Parses consecutive wins/losses string such as:
    - '0 (0.00)' -> count=0, amount=0.00
    - '3 (150.50)' -> count=3, amount=150.50
    """
    if raw is None or not str(raw).strip():
        return {"count": None, "amount": None, "raw": raw}

    raw_str = str(raw).strip()
    match = re.search(r"(-?\d+)\s*\(\s*(-?\d+(?:[.,]\d+)?)\s*\)", raw_str)
    if match:
        return {
            "count": int(match.group(1)),
            "amount": float(match.group(2).replace(",", ".")),
            "raw": raw_str,
        }

    return {"count": parse_int(raw_str), "amount": None, "raw": raw_str}


def parse_maximal_consecutive_profit_loss(raw):
    """
    Parses maximal consecutive profit/loss string such as:
    - '0.00 (0)' -> amount=0.00, count=0
    - '250.00 (4)' -> amount=250.00, count=4
    """
    if raw is None or not str(raw).strip():
        return {"amount": None, "count": None, "raw": raw}

    raw_str = str(raw).strip()
    match = re.search(r"(-?\d+(?:[.,]\d+)?)\s*\(\s*(-?\d+)\s*\)", raw_str)
    if match:
        return {
            "amount": float(match.group(1).replace(",", ".")),
            "count": int(match.group(2)),
            "raw": raw_str,
        }

    return {"amount": parse_float(raw_str), "count": None, "raw": raw_str}


def parse_value_and_percent(raw):
    """
    Parses metrics formatted as 'value (percent%)' or just 'value'
    E.g. Z-Score, AHPR, GHPR
    """
    if raw is None or not str(raw).strip():
        return {"value": None, "percent": None, "raw": raw}

    raw_str = str(raw).strip()
    pct = parse_percent(raw_str)
    cleaned = re.sub(r"\(?\s*-?\d+(?:[.,]\d+)?\s*%\s*\)?", "", raw_str).strip().strip("()")
    val = parse_float(cleaned) if cleaned else None

    return {
        "value": val,
        "percent": pct,
        "raw": raw_str,
    }


def read_report_html(report_path):
    report_path = Path(report_path)
    if not report_path.exists():
        raise FileNotFoundError(f"Report not found: {report_path}")

    if report_path.stat().st_size == 0:
        raise ValueError(f"Report is empty: {report_path}")

    raw = report_path.read_bytes()

    # Detect MT5 UTF-16LE encoding (with BOM \xff\xfe or null bytes) vs UTF-8
    if raw.startswith(b"\xff\xfe") or b"\x00" in raw[:100]:
        html = raw.decode("utf-16le", errors="ignore")
    elif raw.startswith(b"\xef\xbb\xbf"):
        html = raw.decode("utf-8-sig", errors="ignore")
    else:
        try:
            html = raw.decode("utf-8")
        except UnicodeDecodeError:
            html = raw.decode("latin-1", errors="ignore")

    if "Strategy Tester Report" not in html:
        raise ValueError(
            "The supplied file does not appear to be an MT5 Strategy Tester report."
        )

    return html


def extract_report_elements(parser_rows):
    """
    Extracts label-value pairs and EA inputs from parsed table rows.
    """
    label_values = {}
    inputs = {}
    in_inputs = False

    for row in parser_rows:
        # Detect inputs section
        if any(c.strip() == "Inputs:" for c in row):
            in_inputs = True
        elif in_inputs and any(c.strip().endswith(":") and c.strip() != "Inputs:" for c in row if c.strip()):
            in_inputs = False

        if in_inputs:
            for cell in row:
                for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)=([^\s]+)", cell):
                    key = match.group(1)
                    if key not in {"Expert", "Symbol", "Period", "Company", "Currency"}:
                        inputs[key] = match.group(2)

        # Extract label-value cell pairs
        i = 0
        while i < len(row):
            cell = row[i].strip()
            if cell.endswith(":"):
                label = cell[:-1].strip()
                val = row[i + 1].strip() if i + 1 < len(row) else ""
                label_values[label] = val
                i += 2
            else:
                i += 1

    return label_values, inputs


def parse_report(report_path):
    report_path = Path(report_path)
    html = read_report_html(report_path)

    parser = MT5ReportHTMLParser()
    parser.feed(html)

    label_values, inputs = extract_report_elements(parser.rows)

    # 1. Settings
    expert = label_values.get("Expert")
    symbol = label_values.get("Symbol")
    period_raw = label_values.get("Period")
    company = label_values.get("Company")
    currency = label_values.get("Currency")
    deposit_raw = label_values.get("Initial Deposit")
    leverage = label_values.get("Leverage")

    timeframe = None
    from_date = None
    to_date = None

    if period_raw:
        match = re.match(
            r"(.+?)\s*\((\d{4}\.\d{2}\.\d{2})\s*-\s*(\d{4}\.\d{2}\.\d{2})\)",
            period_raw,
        )
        if match:
            timeframe = match.group(1).strip()
            from_date = match.group(2)
            to_date = match.group(3)

    initial_deposit = parse_float(deposit_raw)

    # 2. Market / Data
    history_quality = parse_percent(label_values.get("History Quality"))
    bars = parse_int(label_values.get("Bars"))
    ticks = parse_int(label_values.get("Ticks"))
    symbols = parse_int(label_values.get("Symbols"))

    # 3. Performance
    total_net_profit = parse_float(label_values.get("Total Net Profit"))
    gross_profit = parse_float(label_values.get("Gross Profit"))
    gross_loss = parse_float(label_values.get("Gross Loss"))
    profit_factor = parse_float(label_values.get("Profit Factor"))
    expected_payoff = parse_float(label_values.get("Expected Payoff"))
    recovery_factor = parse_float(label_values.get("Recovery Factor"))
    sharpe_ratio = parse_float(label_values.get("Sharpe Ratio"))
    on_tester_result = parse_float(label_values.get("OnTester result"))
    lr_correlation = parse_float(label_values.get("LR Correlation"))
    lr_standard_error = parse_float(label_values.get("LR Standard Error"))
    margin_level = parse_percent(label_values.get("Margin Level")) or parse_float(label_values.get("Margin Level"))
    z_score = parse_value_and_percent(label_values.get("Z-Score"))
    ahpr = parse_value_and_percent(label_values.get("AHPR"))
    ghpr = parse_value_and_percent(label_values.get("GHPR"))

    # 4. Drawdowns
    balance_dd_abs = parse_float(label_values.get("Balance Drawdown Absolute"))
    equity_dd_abs = parse_float(label_values.get("Equity Drawdown Absolute"))
    balance_dd_max = parse_drawdown(label_values.get("Balance Drawdown Maximal"))
    equity_dd_max = parse_drawdown(label_values.get("Equity Drawdown Maximal"))
    balance_dd_rel = parse_drawdown(label_values.get("Balance Drawdown Relative"))
    equity_dd_rel = parse_drawdown(label_values.get("Equity Drawdown Relative"))

    # 5. Trades
    total_trades = parse_int(label_values.get("Total Trades"))
    total_deals = parse_int(label_values.get("Total Deals"))
    short_trades = parse_count_and_percent(label_values.get("Short Trades (won %)"))
    long_trades = parse_count_and_percent(label_values.get("Long Trades (won %)"))
    profit_trades = parse_count_and_percent(label_values.get("Profit Trades (% of total)"))
    loss_trades = parse_count_and_percent(label_values.get("Loss Trades (% of total)"))
    largest_profit = parse_float(label_values.get("Largest profit trade"))
    largest_loss = parse_float(label_values.get("Largest loss trade"))
    average_profit = parse_float(label_values.get("Average profit trade"))
    average_loss = parse_float(label_values.get("Average loss trade"))
    max_consec_wins = parse_consecutive_wins_losses(label_values.get("Maximum consecutive wins ($)"))
    max_consec_losses = parse_consecutive_wins_losses(label_values.get("Maximum consecutive losses ($)"))
    max_consec_profit = parse_maximal_consecutive_profit_loss(label_values.get("Maximal consecutive profit (count)"))
    max_consec_loss = parse_maximal_consecutive_profit_loss(label_values.get("Maximal consecutive loss (count)"))
    avg_consec_wins = parse_float(label_values.get("Average consecutive wins"))
    avg_consec_losses = parse_float(label_values.get("Average consecutive losses"))

    # Correlations & Holding Times
    corr_profit_mfe = parse_float(label_values.get("Correlation (Profits,MFE)"))
    corr_profit_mae = parse_float(label_values.get("Correlation (Profits,MAE)"))
    corr_mfe_mae = parse_float(label_values.get("Correlation (MFE,MAE)"))
    min_holding_time = label_values.get("Minimal position holding time")
    max_holding_time = label_values.get("Maximal position holding time")
    avg_holding_time = label_values.get("Average position holding time")

    metrics = {
        # Market / Data
        "history_quality_percent": history_quality,
        "bars": bars,
        "ticks": ticks,
        "symbols": symbols,

        # Performance
        "total_net_profit": total_net_profit,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": profit_factor,
        "expected_payoff": expected_payoff,
        "recovery_factor": recovery_factor,
        "sharpe_ratio": sharpe_ratio,
        "margin_level": margin_level,
        "z_score": z_score,
        "ahpr": ahpr,
        "ghpr": ghpr,
        "on_tester_result": on_tester_result,
        "lr_correlation": lr_correlation,
        "lr_standard_error": lr_standard_error,

        # Drawdown
        "balance_drawdown_absolute": balance_dd_abs,
        "equity_drawdown_absolute": equity_dd_abs,
        "balance_drawdown_maximal": balance_dd_max,
        "equity_drawdown_maximal": equity_dd_max,
        "balance_drawdown_relative": balance_dd_rel,
        "equity_drawdown_relative": equity_dd_rel,

        # Trades
        "total_trades": total_trades,
        "total_deals": total_deals,
        "short_trades": short_trades,
        "long_trades": long_trades,
        "profit_trades": profit_trades,
        "loss_trades": loss_trades,
        "largest_profit_trade": largest_profit,
        "largest_loss_trade": largest_loss,
        "average_profit_trade": average_profit,
        "average_loss_trade": average_loss,
        "maximum_consecutive_wins": max_consec_wins,
        "maximum_consecutive_losses": max_consec_losses,
        "maximal_consecutive_profit": max_consec_profit,
        "maximal_consecutive_loss": max_consec_loss,
        "average_consecutive_wins": avg_consec_wins,
        "average_consecutive_losses": avg_consec_losses,

        # Additional metrics
        "correlation_profit_mfe": corr_profit_mfe,
        "correlation_profit_mae": corr_profit_mae,
        "correlation_mfe_mae": corr_mfe_mae,
        "minimal_position_holding_time": min_holding_time,
        "maximal_position_holding_time": max_holding_time,
        "average_position_holding_time": avg_holding_time,
    }

    validation = {
        "report_non_empty": report_path.stat().st_size > 0,
        "history_quality_100": (history_quality == 100.0),
        "bars_present": (bars or 0) > 0,
        "ticks_present": (ticks or 0) > 0,
        "test_executed": (
            (bars or 0) > 0
            and (ticks or 0) > 0
            and history_quality is not None
        ),
    }

    result = {
        "schema_version": 1,
        "parser_version": PARSER_VERSION,
        "parsed_at": datetime.now().astimezone().isoformat(),
        "report_file": str(report_path.resolve()),
        "settings": {
            "expert": expert,
            "symbol": symbol,
            "timeframe": timeframe,
            "from": from_date,
            "to": to_date,
            "period_raw": period_raw,
            "inputs": inputs,
            "company": company,
            "currency": currency,
            "initial_deposit": initial_deposit,
            "leverage": leverage,
        },
        "metrics": metrics,
        "validation": validation,
    }

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Parse an MT5 Strategy Tester HTML report."
    )

    parser.add_argument(
        "report",
        help="Path to the MT5 .htm report",
    )

    parser.add_argument(
        "-o",
        "--output",
        help="Output JSON path",
    )

    args = parser.parse_args()

    result = parse_report(args.report)

    if args.output:
        output_path = Path(args.output)
    else:
        report_path = Path(args.report)
        output_path = report_path.with_name(
            f"{report_path.stem}_metrics.json"
        )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )

    print("=" * 60)
    print("MT5 REPORT PARSED")
    print("=" * 60)
    print(f"Report : {args.report}")
    print(f"JSON   : {output_path}")
    print()
    print(f"Expert         : {result['settings']['expert']}")
    print(f"Symbol         : {result['settings']['symbol']}")
    print(f"Timeframe      : {result['settings']['timeframe']}")
    print(f"Period         : {result['settings']['from']} -> {result['settings']['to']}")
    print(f"History Quality: {result['metrics']['history_quality_percent']}%")
    print(f"Bars           : {result['metrics']['bars']}")
    print(f"Ticks          : {result['metrics']['ticks']}")
    print(f"Total Trades   : {result['metrics']['total_trades']}")
    print(f"Total Deals    : {result['metrics']['total_deals']}")
    print(f"Net Profit     : {result['metrics']['total_net_profit']}")
    print(f"Profit Factor  : {result['metrics']['profit_factor']}")
    print(f"Inputs         : {result['settings']['inputs']}")
    print()
    print(f"Test Executed  : {result['validation']['test_executed']}")


if __name__ == "__main__":
    main()
