"""
AI Analysis Module for AU/NZ Economic Dashboard.

Produces:
  - 8-quarter ARIMA forecasts with 80% and 95% confidence intervals
  - Anomaly detection via Isolation Forest
  - Economic regime classification (Expansion / Contraction / Stagflation / Recovery / Crisis)
  - Composite Economic Health Score (0-100) per quarter
  - Correlation matrix across all key indicators
  - Auto-generated natural language insights
"""

import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import MinMaxScaler
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.stattools import adfuller

warnings.filterwarnings("ignore")

OUTPUT_DIR = Path(__file__).parent.parent / "data" / "processed"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _adf_order(series: pd.Series, max_d: int = 2) -> int:
    """Return differencing order needed for stationarity (ADF test)."""
    for d in range(max_d + 1):
        s = series.diff(d).dropna() if d > 0 else series.dropna()
        try:
            p = adfuller(s, autolag="AIC")[1]
            if p < 0.05:
                return d
        except Exception:
            pass
    return 1


def _fit_arima(series: pd.Series, d: int) -> ARIMA:
    """Fit ARIMA(2,d,2) with fallback to (1,d,1)."""
    for order in [(2, d, 2), (1, d, 1), (1, d, 0), (0, d, 1)]:
        try:
            model = ARIMA(series, order=order).fit()
            return model
        except Exception:
            continue
    raise RuntimeError(f"Could not fit ARIMA for series '{series.name}'")


# ---------------------------------------------------------------------------
# Forecasting
# ---------------------------------------------------------------------------

def build_forecasts(datasets: dict) -> pd.DataFrame:
    """Return a DataFrame with 8-period ARIMA forecasts per series."""
    TARGETS = {
        "Cash Rate (%)":         ("au_cash_rate",    "CashRate_Pct",          "ME"),
        "CPI YoY (%)":           ("au_cpi",          "CPI_YoY_Pct",           "QE"),
        "GDP Growth YoY (%)":    ("au_gdp",          "GDP_Growth_YoY_Pct",    "QE"),
        "Unemployment Rate (%)": ("au_labour",        "Unemployment_Rate_Pct", "ME"),
        "OO Housing Rate (%)":   ("au_housing_rates", "OO_Outstanding_All_Pct","ME"),
    }

    rows = []
    for label, (ds, col, freq) in TARGETS.items():
        df = datasets.get(ds)
        if df is None or col not in df.columns:
            continue
        raw = df.set_index("Date")[col].dropna()
        raw = raw[raw.index.year >= 2000]
        # Resample to the target frequency and forward-fill gaps
        series = raw.resample(freq).last().ffill()
        if len(series) < 20:
            continue

        d = _adf_order(series)
        try:
            model = _fit_arima(series, d)
        except Exception as e:
            print(f"    Skipping forecast for {label}: {e}")
            continue

        fc = model.get_forecast(steps=8)
        mean = fc.predicted_mean
        ci80 = fc.conf_int(alpha=0.20)
        ci95 = fc.conf_int(alpha=0.05)

        for i, (date, val) in enumerate(mean.items()):
            rows.append({
                "Series":       label,
                "Forecast_Date": date,
                "Forecast_Value": round(float(val), 4),
                "CI80_Lower":   round(float(ci80.iloc[i, 0]), 4),
                "CI80_Upper":   round(float(ci80.iloc[i, 1]), 4),
                "CI95_Lower":   round(float(ci95.iloc[i, 0]), 4),
                "CI95_Upper":   round(float(ci95.iloc[i, 1]), 4),
                "Model":        f"ARIMA({model.model.order})",
            })

        # Append recent actuals for context
        for date2, val2 in series.tail(12).items():
            rows.append({
                "Series":        label,
                "Forecast_Date": date2,
                "Actual_Value":  round(float(val2), 4),
                "CI80_Lower":    None,
                "CI80_Upper":    None,
                "CI95_Lower":    None,
                "CI95_Upper":    None,
                "Model":         "Actual",
            })

    df_out = pd.DataFrame(rows)
    df_out["Forecast_Date"] = pd.to_datetime(df_out["Forecast_Date"])
    return df_out.sort_values(["Series", "Forecast_Date"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Anomaly Detection
# ---------------------------------------------------------------------------

def detect_anomalies(datasets: dict) -> pd.DataFrame:
    """Flag statistically unusual months/quarters using Isolation Forest."""
    au_lr = datasets.get("au_labour")
    au_gdp = datasets.get("au_gdp")
    au_cpi = datasets.get("au_cpi")
    au_cr  = datasets.get("au_cash_rate")

    # Build quarterly panel
    def _q(df, col):
        return (df.set_index("Date")[col].dropna()
                  .resample("QE").mean()
                  .rename(col))

    parts = [
        _q(au_lr,  "Unemployment_Rate_Pct"),
        _q(au_gdp, "GDP_Growth_YoY_Pct"),
        _q(au_cpi, "CPI_YoY_Pct"),
        _q(au_cr,  "CashRate_Pct"),
    ]
    panel = pd.concat(parts, axis=1).dropna()
    panel = panel[panel.index.year >= 2000]

    scaler = MinMaxScaler()
    scaled = scaler.fit_transform(panel)

    clf = IsolationForest(contamination=0.07, random_state=42)
    panel["Anomaly_Score"] = clf.fit_predict(scaled)   # -1 = anomaly
    panel["Anomaly_Flag"]  = (panel["Anomaly_Score"] == -1).astype(int)

    # Compute Z-scores per column to identify which indicator drove it
    for col in ["Unemployment_Rate_Pct", "GDP_Growth_YoY_Pct", "CPI_YoY_Pct", "CashRate_Pct"]:
        panel[f"Z_{col}"] = (panel[col] - panel[col].mean()) / panel[col].std()

    panel = panel.reset_index().rename(columns={"Date": "Quarter"})
    panel["Quarter"] = pd.to_datetime(panel["Quarter"])

    def _driver(row):
        if row["Anomaly_Flag"] == 0:
            return ""
        z_cols = [c for c in panel.columns if c.startswith("Z_")]
        vals = {c: abs(row[c]) for c in z_cols}
        top = max(vals, key=vals.get)
        return top.replace("Z_", "").replace("_", " ")

    panel["Primary_Driver"] = panel.apply(_driver, axis=1)
    return panel.drop(columns=["Anomaly_Score"])


# ---------------------------------------------------------------------------
# Economic Regime Classification
# ---------------------------------------------------------------------------

def classify_regimes(datasets: dict) -> pd.DataFrame:
    """Label each quarter as an economic regime."""
    au_gdp = datasets["au_gdp"]
    au_cpi = datasets["au_cpi"]
    au_lr  = datasets["au_labour"]

    gdp = au_gdp.set_index("Date")["GDP_Growth_YoY_Pct"].resample("QE").last()
    cpi = au_cpi.set_index("Date")["CPI_YoY_Pct"].resample("QE").last()
    unemp = au_lr.set_index("Date")["Unemployment_Rate_Pct"].resample("QE").last()

    panel = pd.concat({"GDP_Growth": gdp, "CPI_YoY": cpi, "Unemployment": unemp}, axis=1).dropna()
    panel = panel[panel.index.year >= 2000]

    def _regime(row):
        g = row["GDP_Growth"]
        c = row["CPI_YoY"]
        u = row["Unemployment"]
        u_chg = row.get("Unemp_Change", 0)
        if g < 0 and u_chg > 0.3:
            return "Crisis"
        if g < 0:
            return "Contraction"
        if g < 1.5 and c > 5:
            return "Stagflation"
        if g > 3 and c < 4 and u < 5.5:
            return "Expansion"
        if g > 0 and u_chg < -0.2:
            return "Recovery"
        return "Moderate Growth"

    panel["Unemp_Change"] = panel["Unemployment"].diff()
    panel["Regime"] = panel.apply(_regime, axis=1)

    REGIME_SCORE = {
        "Expansion":      90,
        "Moderate Growth": 65,
        "Recovery":       55,
        "Stagflation":    35,
        "Contraction":    25,
        "Crisis":          5,
    }
    panel["Regime_Score"] = panel["Regime"].map(REGIME_SCORE)
    return panel.reset_index().rename(columns={"Date": "Quarter"})


# ---------------------------------------------------------------------------
# Composite Economic Health Score
# ---------------------------------------------------------------------------

def compute_health_score(datasets: dict) -> pd.DataFrame:
    """
    0–100 score weighting:
      GDP growth       25 pts  (higher is better)
      Unemployment     20 pts  (lower is better)
      Inflation        20 pts  (target 2-3% is best)
      Cash Rate        15 pts  (moderate rate preferred)
      Employment growth 20 pts (higher is better)
    """
    au_gdp  = datasets["au_gdp"]
    au_cpi  = datasets["au_cpi"]
    au_lr   = datasets["au_labour"]
    au_cr   = datasets["au_cash_rate"]

    gdp   = au_gdp.set_index("Date")["GDP_Growth_YoY_Pct"].resample("QE").last()
    cpi   = au_cpi.set_index("Date")["CPI_YoY_Pct"].resample("QE").last()
    unemp = au_lr.set_index("Date")["Unemployment_Rate_Pct"].resample("QE").last()
    empl_g = au_lr.set_index("Date")["Employment_Growth_YoY_Pct"].resample("QE").last()
    cr    = au_cr.set_index("Date")["CashRate_Pct"].resample("QE").last()

    panel = pd.concat({
        "GDP_Growth": gdp,
        "CPI_YoY":    cpi,
        "Unemployment": unemp,
        "Employment_Growth": empl_g,
        "Cash_Rate": cr,
    }, axis=1).dropna(subset=["GDP_Growth", "CPI_YoY", "Unemployment"])
    panel = panel[panel.index.year >= 2000]

    def _gdp_score(g):
        if g >= 4:   return 25
        if g >= 2.5: return 20
        if g >= 1:   return 14
        if g >= 0:   return 7
        return 0

    def _unemp_score(u):
        if u <= 4:   return 20
        if u <= 5:   return 16
        if u <= 6:   return 10
        if u <= 8:   return 5
        return 0

    def _cpi_score(c):
        if 2 <= c <= 3:   return 20
        if 1 <= c <= 4:   return 15
        if 0 <= c <= 5:   return 8
        if c < 0:         return 4
        return 2

    def _empl_score(e):
        if pd.isna(e): return 10
        if e >= 3:   return 20
        if e >= 1.5: return 16
        if e >= 0:   return 10
        return 3

    def _rate_score(r):
        if pd.isna(r): return 8
        if 2 <= r <= 4:  return 15
        if 1 <= r <= 6:  return 10
        return 5

    panel["S_GDP"]         = panel["GDP_Growth"].apply(_gdp_score)
    panel["S_Unemployment"]= panel["Unemployment"].apply(_unemp_score)
    panel["S_CPI"]         = panel["CPI_YoY"].apply(_cpi_score)
    panel["S_Employment"]  = panel["Employment_Growth"].apply(_empl_score)
    panel["S_Rate"]        = panel["Cash_Rate"].apply(_rate_score)

    panel["Health_Score"] = (
        panel["S_GDP"] + panel["S_Unemployment"] + panel["S_CPI"] +
        panel["S_Employment"] + panel["S_Rate"]
    )
    panel["Health_Label"] = pd.cut(
        panel["Health_Score"],
        bins=[0, 30, 50, 65, 80, 100],
        labels=["Poor", "Below Average", "Average", "Good", "Excellent"],
    )
    return panel.reset_index().rename(columns={"Date": "Quarter"})


# ---------------------------------------------------------------------------
# Correlation Matrix
# ---------------------------------------------------------------------------

def build_correlations(datasets: dict) -> pd.DataFrame:
    """Quarterly correlation matrix across all key Australian indicators."""
    au_gdp  = datasets["au_gdp"]
    au_cpi  = datasets["au_cpi"]
    au_lr   = datasets["au_labour"]
    au_cr   = datasets["au_cash_rate"]
    au_hr   = datasets["au_housing_rates"]

    parts = {
        "GDP_Growth (%)":        au_gdp.set_index("Date")["GDP_Growth_YoY_Pct"].resample("QE").last(),
        "CPI_YoY (%)":           au_cpi.set_index("Date")["CPI_YoY_Pct"].resample("QE").last(),
        "Unemployment (%)":       au_lr.set_index("Date")["Unemployment_Rate_Pct"].resample("QE").last(),
        "Cash_Rate (%)":          au_cr.set_index("Date")["CashRate_Pct"].resample("QE").last(),
        "OO_Mortgage_Rate (%)":   au_hr.set_index("Date")["OO_Outstanding_All_Pct"].resample("QE").last(),
        "Participation_Rate (%)": au_lr.set_index("Date")["Participation_Rate_Pct"].resample("QE").last(),
    }
    panel = pd.concat(parts, axis=1).dropna()
    panel = panel[panel.index.year >= 2000]
    corr = panel.corr().round(3)
    corr_df = corr.reset_index().rename(columns={"index": "Indicator"})
    return corr_df


# ---------------------------------------------------------------------------
# AU vs NZ Comparison
# ---------------------------------------------------------------------------

def build_comparison(datasets: dict) -> pd.DataFrame:
    wb_au = datasets["wb_au"]
    wb_nz = datasets["wb_nz"]
    combined = pd.concat([wb_au, wb_nz], ignore_index=True)
    combined = combined[combined["Year"] >= 2000]
    combined["GDP_Billion_USD"] = (combined["gdp_usd"] / 1e9).round(2)
    combined["GDP_per_Capita_USD"] = combined["gdp_per_capita"].round(0)
    combined["CPI_Inflation_Pct"] = combined["cpi_inflation"].round(2)
    combined["Unemployment_Pct"] = combined["unemployment"].round(2)
    combined["Population_M"] = (combined["population"] / 1e6).round(2)
    combined["Current_Account_pct_GDP"] = combined["current_account"].round(2)
    return combined[["Year","Country","Country_Code","GDP_Billion_USD","GDP_per_Capita_USD",
                      "CPI_Inflation_Pct","Unemployment_Pct","Population_M","Current_Account_pct_GDP",
                      "exports_pct_gdp","fdi_inflows","govt_debt_pct_gdp"]].sort_values(["Year","Country"])


# ---------------------------------------------------------------------------
# Natural Language Insights  (template fallback — used when Claude is unavailable)
# ---------------------------------------------------------------------------

def _template_insights(datasets: dict, health_df: pd.DataFrame, regime_df: pd.DataFrame) -> pd.DataFrame:
    insights = []

    # Current cash rate
    cr = datasets["au_cash_rate"].tail(1)
    if not cr.empty:
        rate = cr["CashRate_Pct"].values[0]
        date = cr["Date"].values[0]
        insights.append({
            "Category": "Interest Rates",
            "Insight": f"The RBA cash rate as of {pd.to_datetime(date).strftime('%b %Y')} is {rate:.2f}%.",
            "Significance": "High",
        })

    # Cash rate trend
    cr_recent = datasets["au_cash_rate"].tail(24)
    if len(cr_recent) >= 12:
        r_now = cr_recent["CashRate_Pct"].iloc[-1]
        r_12m = cr_recent["CashRate_Pct"].iloc[-12]
        chg = r_now - r_12m
        direction = "risen" if chg > 0 else "fallen"
        insights.append({
            "Category": "Interest Rates",
            "Insight": f"The cash rate has {direction} by {abs(chg):.2f} percentage points over the past 12 months.",
            "Significance": "High" if abs(chg) > 0.5 else "Medium",
        })

    # Latest inflation
    cpi = datasets["au_cpi"].tail(1)
    if not cpi.empty:
        inf = cpi["CPI_YoY_Pct"].values[0]
        target = "within" if 2 <= inf <= 3 else "outside"
        insights.append({
            "Category": "Inflation",
            "Insight": f"Australian CPI inflation is {inf:.1f}% YoY — {target} the RBA 2–3% target band.",
            "Significance": "High" if abs(inf - 2.5) > 1.5 else "Medium",
        })

    # Unemployment
    unemp = datasets["au_labour"].tail(1)
    if not unemp.empty:
        u = unemp["Unemployment_Rate_Pct"].values[0]
        level = "near historic lows" if u < 4.5 else ("elevated" if u > 6 else "moderate")
        insights.append({
            "Category": "Employment",
            "Insight": f"Australian unemployment is {u:.1f}% — {level} by historical standards.",
            "Significance": "High" if u > 6 or u < 3.8 else "Medium",
        })

    # Current economic regime
    if not regime_df.empty:
        latest_r = regime_df.iloc[-1]
        insights.append({
            "Category": "Economic Regime",
            "Insight": f"Latest economic regime classification: '{latest_r['Regime']}' (Q{latest_r['Quarter'].quarter} {latest_r['Quarter'].year})",
            "Significance": "High" if latest_r["Regime"] in ("Crisis", "Contraction") else "Medium",
        })

    # Health score trend
    if len(health_df) >= 4:
        h_now  = health_df["Health_Score"].iloc[-1]
        h_4q   = health_df["Health_Score"].iloc[-4]
        trend  = "improved" if h_now > h_4q else "declined"
        insights.append({
            "Category": "Economic Health",
            "Insight": f"Australia's composite health score is {h_now:.0f}/100 ({health_df['Health_Label'].iloc[-1]}), {trend} from {h_4q:.0f} a year ago.",
            "Significance": "High" if abs(h_now - h_4q) > 10 else "Medium",
        })

    # Housing mortgage rate spread
    hr = datasets["au_housing_rates"].tail(1)
    cr_latest = datasets["au_cash_rate"].tail(1)
    if not hr.empty and not cr_latest.empty:
        mortgage = hr["OO_Outstanding_All_Pct"].values[0]
        cash = cr_latest["CashRate_Pct"].values[0]
        spread = mortgage - cash
        insights.append({
            "Category": "Housing",
            "Insight": f"Current spread: owner-occupier mortgage rate ({mortgage:.2f}%) is {spread:.2f}pp above the cash rate ({cash:.2f}%).",
            "Significance": "Medium",
        })

    # AU vs NZ GDP growth comparison (latest available year)
    if not datasets["wb_au"].empty and not datasets["wb_nz"].empty:
        au_g = datasets["wb_au"].dropna(subset=["gdp_growth"]).tail(1)
        nz_g = datasets["wb_nz"].dropna(subset=["gdp_growth"]).tail(1)
        if not au_g.empty and not nz_g.empty:
            au_val = au_g["gdp_growth"].values[0]
            nz_val = nz_g["gdp_growth"].values[0]
            yr     = int(au_g["Year"].values[0])
            faster = "Australia" if au_val > nz_val else "New Zealand"
            insights.append({
                "Category": "AU vs NZ",
                "Insight": f"In {yr}: Australia GDP growth {au_val:.1f}% vs NZ {nz_val:.1f}%. {faster} growing faster.",
                "Significance": "Medium",
            })

    return pd.DataFrame(insights)


def generate_insights(
    datasets: dict,
    health_df: pd.DataFrame,
    regime_df: pd.DataFrame,
    anomaly_df: pd.DataFrame | None = None,
    forecast_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Try Claude API first; fall back to template insights if unavailable.
    """
    if anomaly_df is None:
        anomaly_df = pd.DataFrame()
    if forecast_df is None:
        forecast_df = pd.DataFrame()

    try:
        from ai_insights_claude import generate_claude_insights
        claude_df = generate_claude_insights(datasets, health_df, regime_df, anomaly_df, forecast_df)
        if not claude_df.empty:
            return claude_df
    except Exception as e:
        print(f"  [Claude] Could not load Claude module: {e}")

    print("  Using template insights (no Claude API key).")
    return _template_insights(datasets, health_df, regime_df)


# ---------------------------------------------------------------------------
# Master analysis runner
# ---------------------------------------------------------------------------

def run_analysis(datasets: dict) -> dict[str, pd.DataFrame]:
    print("\n=== Running AI Analysis ===")

    print("  Building ARIMA forecasts...")
    forecasts = build_forecasts(datasets)
    print(f"    {len(forecasts)} forecast rows")

    print("  Detecting anomalies...")
    anomalies = detect_anomalies(datasets)
    flagged = anomalies["Anomaly_Flag"].sum()
    print(f"    {flagged} anomalous quarters detected")

    print("  Classifying economic regimes...")
    regimes = classify_regimes(datasets)
    print(f"    {regimes['Regime'].value_counts().to_dict()}")

    print("  Computing health scores...")
    health = compute_health_score(datasets)
    print(f"    Latest score: {health['Health_Score'].iloc[-1]:.0f}/100 ({health['Health_Label'].iloc[-1]})")

    print("  Building correlation matrix...")
    correlations = build_correlations(datasets)

    print("  Comparing AU vs NZ...")
    comparison = build_comparison(datasets)

    print("  Generating natural language insights...")
    insights = generate_insights(datasets, health, regimes, anomalies, forecasts)

    results = {
        "forecasts":    forecasts,
        "anomalies":    anomalies,
        "regimes":      regimes,
        "health":       health,
        "correlations": correlations,
        "comparison":   comparison,
        "insights":     insights,
    }

    for name, df in results.items():
        path = OUTPUT_DIR / f"{name}.csv"
        df.to_csv(path, index=False)

    return results


if __name__ == "__main__":
    from fetch_data import fetch_all
    datasets = fetch_all()
    run_analysis(datasets)
