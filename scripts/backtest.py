import json
import subprocess
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.json"


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as file:
        return json.load(file)


def create_tester_config(config):
    tester_config_path = (
        PROJECT_ROOT
        / "tester"
        / "configs"
        / "backtest.ini"
    )

    tester_config_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    # MT5 terminal and data locations
    terminal = Path(config["mt5_terminal"])
    if not terminal.exists():
        raise FileNotFoundError(
            f"MT5 terminal not found:\n{terminal}"
        )

    mt5_data = Path(config["mt5_data"])
    if not mt5_data.exists():
        raise FileNotFoundError(
            f"MT5 data directory not found:\n{mt5_data}"
        )

    # In standard MT5 mode, the tester writes reports relative to the MT5 Data Directory
    report_name = config["output"]["report"]
    report_path = mt5_data / report_name

    # Ensure EA is present in MT5 data directory MQL5/Experts
    ea_name = config["ea"]["name"]
    project_ea = PROJECT_ROOT / "ea" / f"{ea_name}.ex5"
    mt5_experts_dir = mt5_data / "MQL5" / "Experts"
    mt5_experts_dir.mkdir(parents=True, exist_ok=True)
    target_ea = mt5_experts_dir / f"{ea_name}.ex5"
    if project_ea.exists():
        import shutil
        shutil.copy2(project_ea, target_ea)

    backtest = config["backtest"]
    # MT5 Strategy Tester expects Expert path relative to MQL5\Experts
    clean_ea = ea_name.replace("Experts\\", "").replace("Experts/", "")
    expert_param = f"{clean_ea}.ex5" if not clean_ea.endswith(".ex5") else clean_ea

    tester_config = f"""[Tester]
Expert={expert_param}
Symbol={backtest["symbol"]}
Period={backtest["timeframe"]}
Model={backtest["model"]}
FromDate={backtest["from"]}
ToDate={backtest["to"]}
Deposit={backtest["deposit"]}
Currency={backtest["currency"]}
Leverage={backtest["leverage"]}
Optimization=0
Report={report_name}
ReplaceReport=1
ShutdownTerminal=1
"""

    tester_config_path.write_text(
        tester_config,
        encoding="utf-8"
    )

    return tester_config_path, report_path


def check_port_conflict():
    """
    Checks if port 3000 is occupied.
    MT5 Strategy Tester on-demand agent (Core 1) requires local port 3000.
    If port 3000 is occupied (e.g. by Next.js), the testing agent cannot bind
    and Strategy Tester fails with 0 bars / 0 ticks.
    """
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.connect(("127.0.0.1", 3000))
            # Port 3000 is occupied
            occupant = ""
            try:
                import subprocess
                out = subprocess.check_output(
                    ["powershell", "-NoProfile", "-Command",
                     "Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { $p = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue; \"PID $($_.OwningProcess) ($($p.ProcessName))\" }"],
                    text=True,
                    timeout=3
                ).strip()
                if out:
                    occupant = f" (occupied by {out})"
            except Exception:
                pass

            print()
            print("!" * 60)
            print("WARNING: Port 3000 is currently in use!" + occupant)
            print("MT5 Strategy Tester requires local port 3000 for Core 1.")
            print("If port 3000 is in use (e.g., by a Next.js/Node dev server),")
            print("MT5 will not be able to start its testing agent and the test")
            print("will complete with 0 bars and 0 ticks.")
            print("!" * 60)
            print()
            return False
        except Exception:
            return True


def run_backtest(config, tester_config_path):
    terminal = Path(config["mt5_terminal"])

    print("=" * 60)
    print("AI EA LAB - AUTOMATED BACKTEST")
    print("=" * 60)
    print()

    # Pre-flight check on port 3000
    check_port_conflict()

    print(f"Terminal : {terminal}")
    print(f"EA       : {config['ea']['name']}")
    print(f"Symbol   : {config['backtest']['symbol']}")
    print(f"Timeframe: {config['backtest']['timeframe']}")
    print(
        f"Period   : "
        f"{config['backtest']['from']} -> "
        f"{config['backtest']['to']}"
    )

    print()
    print("Starting MT5 Strategy Tester...")
    print()

    command = [
        str(terminal),
        f"/config:{tester_config_path}"
    ]

    process = subprocess.Popen(command)

    print(
        f"MT5 process started "
        f"(PID: {process.pid})"
    )

    while process.poll() is None:
        print(
            "Backtest running...",
            end="\r"
        )
        time.sleep(2)

    print()
    print("MT5 process finished.")

    return process.returncode


def verify_report(report_path):
    print()
    print("Checking for backtest report...")

    if not report_path.exists():
        print()
        print("WARNING: Backtest completed,")
        print("but the expected report was not found.")
        print()
        print("Expected report:")
        print(report_path)

        return False

    file_size = report_path.stat().st_size

    print()
    print("Report found!")
    print(f"Path: {report_path}")
    print(f"Size: {file_size} bytes")

    if file_size == 0:
        print()
        print("WARNING: Report exists but is empty.")

        return False

    # Check report content to confirm the Strategy Tester actually ran
    try:
        raw_bytes = report_path.read_bytes()
        # MT5 reports are typically UTF-16LE with BOM
        if raw_bytes.startswith(b"\xff\xfe") or b"\x00" in raw_bytes[:100]:
            content = raw_bytes.decode("utf-16le", errors="ignore")
        else:
            content = raw_bytes.decode("utf-8", errors="ignore")

        import re
        bars_match = re.search(r"Bars:\s*</td>\s*<td[^>]*><b>(\d+)</b>", content)
        ticks_match = re.search(r"Ticks:\s*</td>\s*<td[^>]*><b>(\d+)</b>", content)
        profit_match = re.search(r"Total Net Profit:\s*</td>\s*<td[^>]*><b>([^<]+)</b>", content)
        history_quality = re.search(r"History Quality:\s*</td>\s*<td[^>]*><b>([^<]+)</b>", content)

        if bars_match and ticks_match:
            bars = int(bars_match.group(1))
            ticks = int(ticks_match.group(1))
            print("Backtest metrics:")
            print(f"  Bars            : {bars}")
            print(f"  Ticks           : {ticks}")
            if history_quality:
                print(f"  History Quality : {history_quality.group(1)}")
            if profit_match:
                print(f"  Total Net Profit: {profit_match.group(1)}")

            if bars == 0 and ticks == 0:
                print()
                print("WARNING: Strategy Tester generated a report shell,")
                print("but 0 bars and 0 ticks were processed (test failed to actually run).")
                return False
    except Exception as e:
        print(f"Note: Could not parse report metrics: {e}")

    # Copy report and associated chart files into project tester/reports
    project_reports_dir = PROJECT_ROOT / "tester" / "reports"
    project_reports_dir.mkdir(parents=True, exist_ok=True)
    dest_report = project_reports_dir / report_path.name
    import shutil
    shutil.copy2(report_path, dest_report)
    print(f"Report copied to project: {dest_report}")

    stem = report_path.stem
    for asset in report_path.parent.glob(f"{stem}*.png"):
        shutil.copy2(asset, project_reports_dir / asset.name)

    return True


def main():
    config = load_config()

    tester_config, report_path = (
        create_tester_config(config)
    )

    print("Tester config created:")
    print(tester_config)

    print()
    print("Expected report:")
    print(report_path)

    print()

    return_code = run_backtest(
        config,
        tester_config
    )

    print()
    print("=" * 60)

    if return_code == 0:
        print("Backtest process completed.")
    else:
        print(
            f"Backtest process exited "
            f"with code: {return_code}"
        )

    print("=" * 60)

    print()

    report_found = verify_report(report_path)

    if not report_found:
        raise SystemExit(
            "Backtest finished but a valid report "
            "was not created."
        )

    print()
    print("=" * 60)
    print("BACKTEST REPORT VERIFIED")
    print("=" * 60)


if __name__ == "__main__":
    main()