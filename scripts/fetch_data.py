"""
Fetches AU/NZ economic data from:
  - Reserve Bank of Australia (RBA) statistical tables (direct CSV/XLSX)
  - World Bank Open Data API (no key required)
"""

import csv
import io
import json
import time
from pathlib import Path

import pandas as pd
import requests

RAW_DIR = Path(__file__).parent.parent / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {"User-Agent": "Mozilla/5.0 (AU-NZ-PowerBI-Dashboard/1.0)"}

RBA_TABLES = {
    "cash_rate":     "https://www.rba.gov.au/statistics/tables/xls/f01hist.xlsx",
    "cpi":           "https://www.rba.gov.au/statistics/tables/csv/g1-data.csv",
    "gdp":           "https://www.rba.gov.au/statistics/tables/csv/h1-data.csv",
    "labour":        "https://www.rba.gov.au/statistics/tables/csv/h5-data.csv",
    "housing_rates": "https://www.rba.gov.au/statistics/tables/csv/f6-data.csv",
}

WB_BASE = (
    "https://api.worldbank.org/v2/country/{country}/indicator/{indicator}"
    "?format=json&per_page=60&mrv=60"
)
WB_INDICATORS = {
    "gdp_usd":           "NY.GDP.MKTP.CD",
    "gdp_growth":        "NY.GDP.MKTP.KD.ZG",
    "gdp_per_capita":    "NY.GDP.PCAP.CD",
    "cpi_inflation":     "FP.CPI.TOTL.ZG",
    "unemployment":      "SL.UEM.TOTL.ZS",
    "population":        "SP.POP.TOTL",
    "current_account":   "BN.CAB.XOKA.GD.ZS",
    "exports_pct_gdp":   "NE.EXP.GNFS.ZS",
    "fdi_inflows":       "BX.KLT.DINV.WD.GD.ZS",
    "govt_debt_pct_gdp": "GC.DOD.TOTL.GD.ZS",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get(url: str, retries: int = 3) -> requests.Response:
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
            return r
        except Exception as e:
            if attempt == retries - 1:
                raise
            print(f"  Retry {attempt + 1}/{retries}: {url[:60]}...")
            time.sleep(2)


def _rba_data_rows(content_bytes: bytes) -> pd.DataFrame:
    """
    Parse RBA CSV bytes.
    Row layout (0-based):
      0  = table name
      1  = short title
      2  = description
      3  = frequency
      4  = type
      5  = units
      6  = blank
      7  = blank
      8  = source
      9  = publication date
      10 = series ID
      11+ = data  (date, val, val, ...)
    Uses skiprows=11 to land directly on data rows.
    Returns DataFrame with integer column indices [0, 1, 2, ...].
    """
    text = content_bytes.decode("utf-8-sig", errors="replace")
    # skiprows=10 keeps the Series-ID row as row 0, which establishes
    # the correct column count for all subsequent sparse rows.
    df = pd.read_csv(
        io.StringIO(text),
        skiprows=10,
        header=None,
        on_bad_lines="skip",
        dtype=object,
    )
    # Row 0 is the Series IDs row — drop it
    df = df.iloc[1:].reset_index(drop=True)
    # Parse dates and filter
    dates = pd.to_datetime(df.iloc[:, 0], dayfirst=True, errors="coerce")
    df = df.copy()
    df[0] = dates
    df = df[df[0].notna()]
    df = df[df[0].dt.year >= 1990]
    for col in df.columns[1:]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.sort_values(0).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Individual fetch functions (column indices validated against live data)
# ---------------------------------------------------------------------------

def fetch_rba_cash_rate() -> pd.DataFrame:
    """Monthly RBA cash rate from F1 Excel file."""
    print("  Fetching RBA cash rate (F1 XLSX)...")
    r = _get(RBA_TABLES["cash_rate"])
    raw = pd.read_excel(io.BytesIO(r.content), header=None, sheet_name=0)
    # Locate first data row (where col 0 is a parseable date)
    data_start = 0
    for i, row in raw.iterrows():
        val = str(row.iloc[0])
        if "/" in val or "-" in val:
            try:
                pd.to_datetime(val, dayfirst=True)
                data_start = i
                break
            except Exception:
                continue
    df = raw.iloc[data_start:, [0, 1]].copy()
    df.columns = ["Date", "CashRate_Pct"]
    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    df["CashRate_Pct"] = pd.to_numeric(df["CashRate_Pct"], errors="coerce")
    df = df.dropna().sort_values("Date")
    df = df[df["Date"].dt.year >= 1990]
    # Resample to end-of-month
    df = df.set_index("Date").resample("ME").last().reset_index()
    df["Date"] = df["Date"].dt.to_period("M").dt.to_timestamp()
    return df.reset_index(drop=True)


def fetch_rba_cpi() -> pd.DataFrame:
    """
    Quarterly CPI from G1.
    Col 1 = CPI index (All groups)
    Col 2 = CPI YoY % change
    """
    print("  Fetching RBA CPI (G1)...")
    r = _get(RBA_TABLES["cpi"])
    df = _rba_data_rows(r.content)
    out = df.iloc[:, [0, 1, 2]].copy()
    out.columns = ["Date", "CPI_Index", "CPI_YoY_Pct"]
    return out.dropna(subset=["CPI_YoY_Pct"]).reset_index(drop=True)


def fetch_rba_gdp() -> pd.DataFrame:
    """
    Quarterly GDP from H1.
    Col 1 = Real GDP chain volume (AUD million)
    Col 2 = Real GDP YoY growth %
    """
    print("  Fetching RBA GDP (H1)...")
    r = _get(RBA_TABLES["gdp"])
    df = _rba_data_rows(r.content)
    out = df.iloc[:, [0, 1, 2]].copy()
    out.columns = ["Date", "GDP_AUD_Million", "GDP_Growth_YoY_Pct"]
    return out.dropna(subset=["GDP_AUD_Million"]).reset_index(drop=True)


def fetch_rba_labour() -> pd.DataFrame:
    """
    Monthly Labour Force from H5.
    Col 1  = Labour force (000)
    Col 2  = Participation rate %
    Col 5  = Employed persons (000)
    Col 6  = Employment YoY growth %
    Col 10 = Unemployment rate %
    """
    print("  Fetching RBA Labour Force (H5)...")
    r = _get(RBA_TABLES["labour"])
    df = _rba_data_rows(r.content)
    out = df.iloc[:, [0, 1, 2, 5, 6, 10]].copy()
    out.columns = [
        "Date", "Labour_Force_000", "Participation_Rate_Pct",
        "Employment_000", "Employment_Growth_YoY_Pct", "Unemployment_Rate_Pct",
    ]
    return out.dropna(subset=["Unemployment_Rate_Pct"]).reset_index(drop=True)


def fetch_rba_housing_rates() -> pd.DataFrame:
    """
    Monthly Housing Lending Rates from F6.
    Col 2  = Outstanding OO All institutions
    Col 4  = Outstanding OO Variable All institutions
    Col 12 = New OO All institutions
    Col 33 = Outstanding Investment All institutions
    Col 43 = New Investment All institutions
    """
    print("  Fetching RBA Housing Lending Rates (F6)...")
    r = _get(RBA_TABLES["housing_rates"])
    df = _rba_data_rows(r.content)
    col_map = {
        2:  "OO_Outstanding_All_Pct",
        4:  "OO_Outstanding_Variable_Pct",
        12: "OO_New_All_Pct",
        33: "Inv_Outstanding_All_Pct",
        43: "Inv_New_All_Pct",
    }
    available = [c for c in col_map if c < len(df.columns)]
    out = df.iloc[:, [0] + available].copy()
    out.columns = ["Date"] + [col_map[c] for c in available]
    return out.dropna(subset=["OO_Outstanding_All_Pct"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# World Bank
# ---------------------------------------------------------------------------

def fetch_worldbank(country: str) -> pd.DataFrame:
    print(f"  Fetching World Bank data for {country}...")
    frames: dict[str, pd.DataFrame] = {}
    for name, indicator in WB_INDICATORS.items():
        url = WB_BASE.format(country=country, indicator=indicator)
        for attempt in range(3):
            try:
                r = requests.get(url, headers=HEADERS, timeout=40)
                r.raise_for_status()
                payload = r.json()
                if len(payload) > 1 and payload[1]:
                    records = [
                        {"Year": int(rec["date"]), name: rec["value"]}
                        for rec in payload[1]
                        if rec["value"] is not None
                    ]
                    if records:
                        frames[name] = pd.DataFrame(records).set_index("Year")
                break
            except Exception as e:
                if attempt == 2:
                    print(f"    Warning: {name} for {country}: {type(e).__name__}")
                else:
                    time.sleep(3)
        time.sleep(0.2)

    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames.values(), axis=1).reset_index()
    df = df.sort_values("Year").reset_index(drop=True)
    df["Country"] = "Australia" if country == "AU" else "New Zealand"
    df["Country_Code"] = country
    return df


# ---------------------------------------------------------------------------
# Master fetch
# ---------------------------------------------------------------------------

def fetch_all() -> dict[str, pd.DataFrame]:
    print("\n=== Fetching Australian Data (RBA) ===")
    datasets: dict[str, pd.DataFrame] = {}
    datasets["au_cash_rate"]     = fetch_rba_cash_rate()
    datasets["au_cpi"]           = fetch_rba_cpi()
    datasets["au_gdp"]           = fetch_rba_gdp()
    datasets["au_labour"]        = fetch_rba_labour()
    datasets["au_housing_rates"] = fetch_rba_housing_rates()

    print("\n=== Fetching World Bank Data (AU + NZ) ===")
    datasets["wb_au"] = fetch_worldbank("AU")
    datasets["wb_nz"] = fetch_worldbank("NZ")

    for name, df in datasets.items():
        path = RAW_DIR / f"{name}.csv"
        df.to_csv(path, index=False)
        print(f"  Saved {name}: {len(df):,} rows -> {path.name}")

    return datasets


if __name__ == "__main__":
    fetch_all()
    print("\nData fetch complete.")
