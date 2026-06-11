"""
Real LLM-powered insights via Claude API.

Replaces template-based generate_insights() with genuine Claude analysis.
Requires ANTHROPIC_API_KEY environment variable.

Falls back to template insights silently if the key is missing.
"""

import json
import os
import re
from typing import Optional

import pandas as pd


def _build_data_context(
    datasets: dict,
    health_df: pd.DataFrame,
    regime_df: pd.DataFrame,
    anomaly_df: pd.DataFrame,
    forecast_df: pd.DataFrame,
) -> str:
    """Serialize all current economic data into a compact JSON-style context block."""
    ctx = {}

    # --- Cash rate ---
    cr = datasets["au_cash_rate"]
    latest_cr = cr.tail(1).iloc[0]
    cr_12m_ago = cr[cr["Date"] <= cr["Date"].iloc[-1] - pd.DateOffset(months=12)].tail(1)
    ctx["cash_rate"] = {
        "current_pct": round(float(latest_cr["CashRate_Pct"]), 2),
        "as_of": latest_cr["Date"].strftime("%b %Y"),
        "change_12m_pp": round(
            float(latest_cr["CashRate_Pct"]) - float(cr_12m_ago["CashRate_Pct"].iloc[0]), 2
        ) if not cr_12m_ago.empty else None,
    }

    # --- CPI ---
    cpi = datasets["au_cpi"]
    latest_cpi = cpi.tail(1).iloc[0]
    cpi_12m_ago = cpi[cpi["Date"] <= cpi["Date"].iloc[-1] - pd.DateOffset(months=12)].tail(1)
    ctx["inflation"] = {
        "cpi_yoy_pct": round(float(latest_cpi["CPI_YoY_Pct"]), 1),
        "as_of": latest_cpi["Date"].strftime("%b %Y"),
        "change_12m_pp": round(
            float(latest_cpi["CPI_YoY_Pct"]) - float(cpi_12m_ago["CPI_YoY_Pct"].iloc[0]), 1
        ) if not cpi_12m_ago.empty else None,
        "rba_target_band": "2-3%",
    }

    # --- GDP ---
    gdp = datasets["au_gdp"]
    gdp_valid = gdp.dropna(subset=["GDP_Growth_YoY_Pct"])
    if not gdp_valid.empty:
        latest_gdp = gdp_valid.tail(1).iloc[0]
        ctx["gdp"] = {
            "growth_yoy_pct": round(float(latest_gdp["GDP_Growth_YoY_Pct"]), 1),
            "gdp_aud_bn": round(float(latest_gdp["GDP_AUD_Million"]) / 1000, 1),
            "as_of": latest_gdp["Date"].strftime("%b %Y"),
        }

    # --- Labour ---
    lab = datasets["au_labour"]
    latest_lab = lab.tail(1).iloc[0]
    lab_12m_ago = lab[lab["Date"] <= lab["Date"].iloc[-1] - pd.DateOffset(months=12)].tail(1)
    ctx["labour"] = {
        "unemployment_pct": round(float(latest_lab["Unemployment_Rate_Pct"]), 1),
        "participation_rate_pct": round(float(latest_lab["Participation_Rate_Pct"]), 1),
        "employment_growth_yoy_pct": round(float(latest_lab["Employment_Growth_YoY_Pct"]), 1),
        "as_of": latest_lab["Date"].strftime("%b %Y"),
        "unemployment_change_12m_pp": round(
            float(latest_lab["Unemployment_Rate_Pct"]) - float(lab_12m_ago["Unemployment_Rate_Pct"].iloc[0]), 1
        ) if not lab_12m_ago.empty else None,
    }

    # --- Housing rates ---
    hr = datasets["au_housing_rates"]
    latest_hr = hr.tail(1).iloc[0]
    ctx["housing"] = {
        "oo_outstanding_all_pct": round(float(latest_hr["OO_Outstanding_All_Pct"]), 2),
        "oo_variable_pct": round(float(latest_hr["OO_Outstanding_Variable_Pct"]), 2) if "OO_Outstanding_Variable_Pct" in latest_hr else None,
        "oo_new_all_pct": round(float(latest_hr["OO_New_All_Pct"]), 2) if "OO_New_All_Pct" in latest_hr else None,
        "mortgage_cash_spread_pp": round(
            float(latest_hr["OO_Outstanding_All_Pct"]) - float(latest_cr["CashRate_Pct"]), 2
        ),
        "as_of": latest_hr["Date"].strftime("%b %Y"),
    }

    # --- Health score ---
    if not health_df.empty:
        h_now = health_df.tail(1).iloc[0]
        h_4q = health_df.iloc[-4] if len(health_df) >= 4 else None
        ctx["health_score"] = {
            "current": round(float(h_now["Health_Score"]), 0),
            "label": str(h_now["Health_Label"]),
            "quarter": pd.to_datetime(h_now["Quarter"]).strftime("%b %Y"),
            "change_4q": round(
                float(h_now["Health_Score"]) - float(h_4q["Health_Score"]), 0
            ) if h_4q is not None else None,
        }

    # --- Economic regime ---
    if not regime_df.empty:
        latest_r = regime_df.tail(1).iloc[0]
        regime_counts = regime_df["Regime"].value_counts().to_dict()
        ctx["economic_regime"] = {
            "current": str(latest_r["Regime"]),
            "quarter": pd.to_datetime(latest_r["Quarter"]).strftime("Q%q %Y"),
            "score": int(latest_r["Regime_Score"]),
            "distribution_since_2000": regime_counts,
        }

    # --- Anomalies ---
    if not anomaly_df.empty:
        anom_flagged = anomaly_df[anomaly_df["Anomaly_Flag"] == 1]
        ctx["anomalies"] = {
            "total_flagged": int(anom_flagged.shape[0]),
            "recent_5": [
                {
                    "quarter": pd.to_datetime(row["Quarter"]).strftime("%b %Y"),
                    "driver": row["Primary_Driver"],
                }
                for _, row in anom_flagged.tail(5).iterrows()
            ],
        }

    # --- AU vs NZ comparison (latest WB data) ---
    wb_au = datasets["wb_au"]
    wb_nz = datasets["wb_nz"]
    au_latest = wb_au.dropna(subset=["gdp_growth"]).tail(1)
    nz_latest = wb_nz.dropna(subset=["gdp_growth"]).tail(1)
    if not au_latest.empty and not nz_latest.empty:
        au_r = au_latest.iloc[0]
        nz_r = nz_latest.iloc[0]
        ctx["au_vs_nz"] = {
            "year": int(au_r["Year"]),
            "au_gdp_growth_pct": round(float(au_r["gdp_growth"]), 1),
            "nz_gdp_growth_pct": round(float(nz_r["gdp_growth"]), 1),
            "au_unemployment_pct": round(float(wb_au.dropna(subset=["unemployment"]).tail(1)["unemployment"].iloc[0]), 1) if not wb_au.dropna(subset=["unemployment"]).empty else None,
            "nz_unemployment_pct": round(float(wb_nz.dropna(subset=["unemployment"]).tail(1)["unemployment"].iloc[0]), 1) if not wb_nz.dropna(subset=["unemployment"]).empty else None,
            "au_gdp_bn_usd": round(float(au_r["gdp_usd"]) / 1e9, 0) if pd.notna(au_r.get("gdp_usd")) else None,
            "nz_gdp_bn_usd": round(float(nz_r["gdp_usd"]) / 1e9, 0) if pd.notna(nz_r.get("gdp_usd")) else None,
        }

    # --- ARIMA forecast summaries ---
    if not forecast_df.empty:
        fc_only = forecast_df[forecast_df["Model"] != "Actual"].dropna(subset=["Forecast_Value"])
        summary = {}
        for series, grp in fc_only.groupby("Series"):
            last_actual = forecast_df[
                (forecast_df["Series"] == series) & (forecast_df["Model"] == "Actual")
            ].tail(1)
            next_fc = grp.head(1).iloc[0]
            summary[series] = {
                "current_actual": round(float(last_actual["Actual_Value"].iloc[0]), 2) if not last_actual.empty else None,
                "next_forecast": round(float(next_fc["Forecast_Value"]), 2),
                "next_forecast_date": pd.to_datetime(next_fc["Forecast_Date"]).strftime("%b %Y"),
                "model": next_fc["Model"],
            }
        ctx["arima_forecasts"] = summary

    return json.dumps(ctx, indent=2, default=str)


_SYSTEM_PROMPT = """You are an expert economic analyst specialising in Australian and New Zealand macroeconomics. \
You have access to live data extracted from the Reserve Bank of Australia (RBA) and the World Bank. \
Your job is to generate clear, data-driven insights for a Power BI executive dashboard consumed by finance professionals.

Rules:
- Base every statement on the numbers provided. Do not invent figures.
- Be concise but substantive — each insight should add genuine analytical value.
- Highlight risk factors, policy implications, and cross-market linkages where relevant.
- Return ONLY a valid JSON array. No markdown fences, no preamble, no trailing text.

Output format (JSON array, 10–14 items):
[
  {"category": "<string>", "insight": "<string>", "significance": "High|Medium|Low"},
  ...
]

Categories to cover (use these exact strings):
- "Interest Rates"
- "Inflation"
- "Employment"
- "GDP Growth"
- "Housing Market"
- "Economic Health"
- "Economic Regime"
- "Anomaly Alert"
- "AU vs NZ"
- "Outlook"
"""


def generate_claude_insights(
    datasets: dict,
    health_df: pd.DataFrame,
    regime_df: pd.DataFrame,
    anomaly_df: pd.DataFrame,
    forecast_df: pd.DataFrame,
    model: str = "claude-sonnet-4-6",
    api_key: Optional[str] = None,
) -> pd.DataFrame:
    """
    Call Claude API with real economic data and return a DataFrame of insights.

    Falls back to an empty DataFrame (caller should use template fallback) if
    the Anthropic package isn't installed or the API key is absent.
    """
    key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        print("  [Claude] ANTHROPIC_API_KEY not set — skipping LLM insights.")
        return pd.DataFrame()

    try:
        import anthropic
    except ImportError:
        print("  [Claude] anthropic package not installed. Run: pip install anthropic")
        return pd.DataFrame()

    data_context = _build_data_context(datasets, health_df, regime_df, anomaly_df, forecast_df)

    user_message = (
        "Here is the current AU/NZ economic data snapshot (JSON):\n\n"
        + data_context
        + "\n\nGenerate 10–14 economic insights as a JSON array following the schema above."
    )

    print(f"  [Claude] Calling {model} for real LLM analysis...")
    client = anthropic.Anthropic(api_key=key)

    try:
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as e:
        print(f"  [Claude] API call failed: {e}")
        return pd.DataFrame()

    raw = response.content[0].text.strip()

    # Strip markdown code fences if the model wrapped them
    raw = re.sub(r"^```[a-z]*\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        items = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"  [Claude] Could not parse JSON response: {e}")
        print(f"  [Claude] Raw output snippet: {raw[:300]}")
        return pd.DataFrame()

    if not isinstance(items, list):
        print("  [Claude] Unexpected response structure (expected list).")
        return pd.DataFrame()

    rows = []
    for item in items:
        if not isinstance(item, dict):
            continue
        rows.append({
            "Category":    str(item.get("category", "General")),
            "Insight":     str(item.get("insight", "")),
            "Significance": str(item.get("significance", "Medium")),
        })

    print(f"  [Claude] Received {len(rows)} insights from {model}.")
    return pd.DataFrame(rows)
