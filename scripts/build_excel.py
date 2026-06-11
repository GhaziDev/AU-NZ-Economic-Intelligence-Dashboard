"""
Builds the Power BI data source Excel workbook.

Sheets produced:
  01_AU_Cash_Rate         Monthly RBA cash rate since 1990
  02_AU_CPI               Quarterly CPI (level + YoY%)
  03_AU_GDP               Quarterly GDP (level + growth%)
  04_AU_Labour            Monthly labour force & unemployment
  05_AU_Housing_Rates     Monthly housing lending rates
  06_WB_AU_Annual         World Bank annual AU indicators
  07_WB_NZ_Annual         World Bank annual NZ indicators
  08_AU_NZ_Comparison     Side-by-side annual AU/NZ metrics
  09_AI_Forecasts         ARIMA 8-period forecasts with CIs
  10_Economic_Regimes     Quarterly regime classification
  11_Health_Score         Quarterly composite 0-100 score
  12_Anomalies            Detected economic anomalies
  13_Correlations         Correlation matrix
  14_AI_Insights          Natural language insight summaries
  15_Date_Table           Calendar dimension (2000-2027)
"""

from pathlib import Path

import pandas as pd
import xlsxwriter

OUTPUT_DIR = Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

WORKBOOK_PATH = OUTPUT_DIR / "AU_NZ_Economic_Intelligence.xlsx"

THEME = {
    "header_bg":   "#1A3A5C",   # dark navy
    "header_font": "#FFFFFF",
    "accent1":     "#2E86AB",   # teal
    "accent2":     "#F18F01",   # amber
    "green":       "#4CAF50",
    "red":         "#E53935",
    "light_bg":    "#F5F7FA",
    "alt_row":     "#EBF0F7",
}


def _add_sheet(wb: xlsxwriter.Workbook, name: str, df: pd.DataFrame):
    ws = wb.add_worksheet(name)

    hdr_fmt = wb.add_format({
        "bold": True, "font_color": THEME["header_font"],
        "bg_color": THEME["header_bg"], "border": 0,
        "align": "center", "valign": "vcenter",
        "font_size": 10, "font_name": "Segoe UI",
    })
    cell_fmt = wb.add_format({
        "font_name": "Segoe UI", "font_size": 9,
        "align": "center", "valign": "vcenter", "border": 0,
    })
    alt_fmt = wb.add_format({
        "font_name": "Segoe UI", "font_size": 9,
        "bg_color": THEME["alt_row"],
        "align": "center", "valign": "vcenter", "border": 0,
    })
    date_fmt = wb.add_format({
        "font_name": "Segoe UI", "font_size": 9,
        "num_format": "yyyy-mm-dd",
        "align": "center", "valign": "vcenter",
    })

    # Header row
    ws.set_row(0, 22)
    for col_idx, col_name in enumerate(df.columns):
        ws.write(0, col_idx, col_name, hdr_fmt)

    # Data rows
    for row_idx, row in enumerate(df.itertuples(index=False), start=1):
        fmt = alt_fmt if row_idx % 2 == 0 else cell_fmt
        ws.set_row(row_idx, 16)
        for col_idx, value in enumerate(row):
            if isinstance(value, pd.Timestamp):
                ws.write_datetime(row_idx, col_idx, value.to_pydatetime(), date_fmt)
            elif pd.isna(value) if not isinstance(value, str) else False:
                ws.write_blank(row_idx, col_idx, None, fmt)
            else:
                ws.write(row_idx, col_idx, value, fmt)

    # Auto-fit columns
    for col_idx, col_name in enumerate(df.columns):
        max_len = max(len(str(col_name)), df[col_name].astype(str).str.len().max())
        ws.set_column(col_idx, col_idx, min(max_len + 2, 40))

    # Freeze header row
    ws.freeze_panes(1, 0)


def _make_date_table() -> pd.DataFrame:
    dates = pd.date_range("2000-01-01", "2027-12-31", freq="D")
    df = pd.DataFrame({"Date": dates})
    df["Year"]          = df["Date"].dt.year
    df["Quarter"]       = df["Date"].dt.quarter
    df["Month"]         = df["Date"].dt.month
    df["Month_Name"]    = df["Date"].dt.strftime("%B")
    df["Week"]          = df["Date"].dt.isocalendar().week.astype(int)
    df["Day_of_Week"]   = df["Date"].dt.day_name()
    df["Is_Weekend"]    = df["Date"].dt.dayofweek >= 5
    df["Quarter_Label"] = "Q" + df["Quarter"].astype(str) + " " + df["Year"].astype(str)
    df["FY_AU"]         = df.apply(
        lambda r: f"FY{r['Year']+1}" if r["Month"] >= 7 else f"FY{r['Year']}", axis=1
    )
    return df


def build_workbook(datasets: dict, analysis: dict):
    print(f"\n=== Building Excel Workbook ===")

    wb = xlsxwriter.Workbook(str(WORKBOOK_PATH), {"default_date_format": "yyyy-mm-dd"})

    # Ensure dates are proper Timestamps for xlsxwriter
    def _prep(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        for col in df.columns:
            if pd.api.types.is_datetime64_any_dtype(df[col]):
                df[col] = pd.to_datetime(df[col])
        return df

    sheets = {
        "01_AU_Cash_Rate":     datasets["au_cash_rate"],
        "02_AU_CPI":           datasets["au_cpi"],
        "03_AU_GDP":           datasets["au_gdp"],
        "04_AU_Labour":        datasets["au_labour"],
        "05_AU_Housing_Rates": datasets["au_housing_rates"],
        "06_WB_AU_Annual":     datasets["wb_au"],
        "07_WB_NZ_Annual":     datasets["wb_nz"],
        "08_AU_NZ_Comparison": analysis["comparison"],
        "09_AI_Forecasts":     analysis["forecasts"],
        "10_Economic_Regimes": analysis["regimes"],
        "11_Health_Score":     analysis["health"],
        "12_Anomalies":        analysis["anomalies"],
        "13_Correlations":     analysis["correlations"],
        "14_AI_Insights":      analysis["insights"],
        "15_Date_Table":       _make_date_table(),
    }

    for sheet_name, df in sheets.items():
        print(f"  Writing sheet: {sheet_name} ({len(df)} rows)")
        _add_sheet(wb, sheet_name, _prep(df))

    # Add a README/cover sheet
    cover = wb.add_worksheet("README")
    bold = wb.add_format({"bold": True, "font_size": 14, "font_name": "Segoe UI", "font_color": THEME["header_bg"]})
    body = wb.add_format({"font_size": 10, "font_name": "Segoe UI"})
    link = wb.add_format({"font_size": 10, "font_name": "Segoe UI", "font_color": THEME["accent1"], "underline": True})

    cover.set_column(0, 0, 70)
    cover.write(0, 0, "AU/NZ Economic Intelligence Dashboard — Data Source", bold)
    cover.write(2, 0, "Generated by: AU-NZ-PowerBI-Dashboard pipeline", body)
    cover.write(3, 0, "Data Sources: Reserve Bank of Australia (RBA) + World Bank Open Data API", body)
    cover.write(5, 0, "Sheets in this workbook:", bold)
    descriptions = [
        ("01_AU_Cash_Rate",     "Monthly RBA cash rate (%) — since 1990"),
        ("02_AU_CPI",           "Quarterly CPI index and year-on-year inflation (%)"),
        ("03_AU_GDP",           "Quarterly real GDP (AUD million) and growth rate (%)"),
        ("04_AU_Labour",        "Monthly employment, unemployment rate, participation rate"),
        ("05_AU_Housing_Rates", "Monthly mortgage lending rates — OO and investment"),
        ("06_WB_AU_Annual",     "World Bank: Australia annual economic indicators"),
        ("07_WB_NZ_Annual",     "World Bank: New Zealand annual economic indicators"),
        ("08_AU_NZ_Comparison", "Side-by-side AU vs NZ key metrics (2000–present)"),
        ("09_AI_Forecasts",     "ARIMA 8-period forecasts with 80% and 95% confidence intervals"),
        ("10_Economic_Regimes", "Quarterly economic regime: Expansion / Contraction / Crisis etc."),
        ("11_Health_Score",     "Composite 0-100 economic health score per quarter"),
        ("12_Anomalies",        "Isolation Forest anomaly detection — flagged quarters"),
        ("13_Correlations",     "Pearson correlation matrix across all indicators"),
        ("14_AI_Insights",      "Auto-generated natural language insights from the data"),
        ("15_Date_Table",       "Date dimension table for Power BI relationships (2000–2027)"),
    ]
    for i, (sheet, desc) in enumerate(descriptions, start=6):
        cover.write(i, 0, f"  • {sheet}: {desc}", body)

    wb.close()
    print(f"\n  Workbook saved: {WORKBOOK_PATH}")
    return WORKBOOK_PATH


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from fetch_data import fetch_all
    from ai_analysis import run_analysis
    datasets = fetch_all()
    analysis = run_analysis(datasets)
    build_workbook(datasets, analysis)
