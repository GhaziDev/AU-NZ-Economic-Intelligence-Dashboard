"""
Master pipeline runner.

Usage:
    python run_pipeline.py                        # full run
    python run_pipeline.py --skip-fetch           # reuse cached data, skip downloads
    python run_pipeline.py --no-claude            # skip Claude API, use template insights
    python run_pipeline.py --output my_file.xlsx  # custom output path
    python run_pipeline.py --skip-fetch --no-claude  # fastest run, fully offline
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "scripts"))

from fetch_data import fetch_all, load_cached
from ai_analysis import run_analysis
from build_excel import build_workbook


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AU/NZ Economic Intelligence Dashboard pipeline"
    )
    parser.add_argument(
        "--skip-fetch",
        action="store_true",
        help="Load data from cached CSVs instead of downloading. Much faster when re-running analysis.",
    )
    parser.add_argument(
        "--no-claude",
        action="store_true",
        help="Skip the Claude API call and use template insights instead.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        metavar="PATH",
        help="Custom path for the output Excel file (default: output/AU_NZ_Economic_Intelligence.xlsx).",
    )
    return parser.parse_args()


def print_banner(args: argparse.Namespace):
    print("=" * 65)
    print("   AU/NZ Economic Intelligence Dashboard  -  AI Pipeline")
    print("   Data: RBA + World Bank  |  AI: ARIMA + IsolationForest")
    print("=" * 65)
    flags = []
    if args.skip_fetch:
        flags.append("cached data")
    if args.no_claude:
        flags.append("no Claude")
    if flags:
        print(f"   Flags: {', '.join(flags)}")
        print("=" * 65)


def print_summary(datasets: dict, analysis: dict):
    print("\n" + "=" * 65)
    print("  PIPELINE SUMMARY")
    print("=" * 65)

    cr = datasets["au_cash_rate"]
    print(f"\n  [AU] RBA Cash Rate:      {cr['CashRate_Pct'].iloc[-1]:.2f}%  ({cr['Date'].iloc[-1].strftime('%b %Y')})")

    cpi = datasets["au_cpi"]
    print(f"  [AU] Inflation (YoY):    {cpi['CPI_YoY_Pct'].iloc[-1]:.1f}%  ({cpi['Date'].iloc[-1].strftime('%b %Y')})")

    gdp = datasets["au_gdp"]
    gdp_g = gdp["GDP_Growth_YoY_Pct"].dropna()
    print(f"  [AU] GDP Growth (YoY):   {gdp_g.iloc[-1]:.1f}%  ({gdp['Date'].iloc[-1].strftime('%b %Y')})")

    lab = datasets["au_labour"]
    print(f"  [AU] Unemployment:       {lab['Unemployment_Rate_Pct'].iloc[-1]:.1f}%  ({lab['Date'].iloc[-1].strftime('%b %Y')})")

    hr = datasets["au_housing_rates"]
    print(f"  [AU] Owner-Occ Rate:     {hr['OO_Outstanding_All_Pct'].iloc[-1]:.2f}%  ({hr['Date'].iloc[-1].strftime('%b %Y')})")

    nz = datasets["wb_nz"].dropna(subset=["gdp_growth"]).tail(1)
    if not nz.empty:
        print(f"\n  [NZ] GDP Growth (WB):    {nz['gdp_growth'].values[0]:.1f}%  ({int(nz['Year'].values[0])})")
    nz_u = datasets["wb_nz"].dropna(subset=["unemployment"]).tail(1)
    if not nz_u.empty:
        print(f"  [NZ] Unemployment (WB):  {nz_u['unemployment'].values[0]:.1f}%  ({int(nz_u['Year'].values[0])})")

    h = analysis["health"]
    print(f"\n  [AI] Health Score:       {h['Health_Score'].iloc[-1]:.0f}/100  ({h['Health_Label'].iloc[-1]})")

    r = analysis["regimes"]
    print(f"  [AI] Economic Regime:    {r['Regime'].iloc[-1]}")

    anom = analysis["anomalies"]
    flagged = anom["Anomaly_Flag"].sum()
    print(f"  [AI] Anomalies (2000+):  {flagged} quarters flagged")

    fc = analysis["forecasts"]
    series_list = fc["Series"].unique()
    print(f"  [AI] Forecast Series:    {len(series_list)}")

    ins = analysis["insights"]
    print(f"  [AI] Insight Lines:      {len(ins)}")

    print("\n  Top Insights:")
    for _, row in ins.iterrows():
        sig = "  " if row["Significance"] == "Medium" else "! "
        print(f"   {sig}[{row['Category']}] {row['Insight']}")


def main():
    args = parse_args()
    start = time.time()
    print_banner(args)

    if args.skip_fetch:
        print("\n[1/3] Loading cached data...")
        datasets = load_cached()
    else:
        print("\n[1/3] Fetching data...")
        datasets = fetch_all()

    print("\n[2/3] Running AI analysis...")
    analysis = run_analysis(datasets, use_claude=not args.no_claude)

    print("\n[3/3] Building Excel workbook...")
    path = build_workbook(datasets, analysis, output_path=args.output)

    print_summary(datasets, analysis)

    elapsed = time.time() - start
    print(f"\n{'='*65}")
    print(f"  Done in {elapsed:.1f}s")
    print(f"  Excel file: {path}")
    print(f"  Open in Power BI Desktop: Get Data -> Excel Workbook")
    print(f"  Setup guide:  powerbi/POWERBI_SETUP.md")
    print(f"{'='*65}\n")


if __name__ == "__main__":
    main()
