# AU/NZ Economic Intelligence Dashboard

A Python pipeline that fetches live Australian and New Zealand economic data, runs statistical analysis and AI-powered insights, and produces an Excel file ready to load into Power BI.

---

## Background

Living in Oceania, I wanted a data-backed way to track the economic issues that directly affect people in Australia and New Zealand, from inflation and interest rates to housing costs and wages. Rather than relying on news headlines, this project pulls the raw numbers from official sources and surfaces the trends, anomalies, and forecasts in one place.

---

## What it does

1. Downloads fresh data from the Reserve Bank of Australia and the World Bank
2. Runs ARIMA forecasting, anomaly detection, and economic regime classification
3. Calls Claude (claude-sonnet-4-6) to generate genuine LLM-written analysis of the data
4. Writes everything into a 15-sheet Excel workbook for Power BI

---

## Requirements

- Python 3.10 or later
- An Anthropic API key (optional, but required for real Claude insights)

Install dependencies:

```
pip install -r requirements.txt
```

---

## How to run

Full run with Claude analysis:

```
$env:ANTHROPIC_API_KEY = "sk-ant-..."
python run_pipeline.py
```

Without Claude (uses template insights):

```
python run_pipeline.py --no-claude
```

Skip downloading and reuse the last cached data (much faster for re-runs):

```
python run_pipeline.py --skip-fetch
```

Fastest offline run (cached data, no Claude):

```
python run_pipeline.py --skip-fetch --no-claude
```

Write the Excel file to a custom location:

```
python run_pipeline.py --output "C:/Reports/my_dashboard.xlsx"
```

The full run takes about 20 seconds. It prints a summary when done.

---

## Data sources

| Source | What it provides | Update frequency |
|--------|-----------------|-----------------|
| RBA F1 | Cash rate (monthly, since 1990) | Monthly |
| RBA G1 | CPI inflation (quarterly) | Quarterly |
| RBA H1 | GDP growth (quarterly) | Quarterly |
| RBA H5 | Unemployment and labour force (monthly) | Monthly |
| RBA F6 | Housing lending rates (monthly, since 2019) | Monthly |
| World Bank API | AU and NZ annual indicators (61 years) | Annual |

No API keys are needed for RBA or World Bank data.

---

## Project structure

```
powerbi_project/
  run_pipeline.py           main script, run this
  requirements.txt
  scripts/
    fetch_data.py           downloads RBA and World Bank data
    ai_analysis.py          ARIMA, anomaly detection, health score, regimes
    ai_insights_claude.py   calls Claude API for LLM-written insights
    build_excel.py          writes the 15-sheet Excel workbook
  output/
    AU_NZ_Economic_Intelligence.xlsx   Power BI data source
  data/
    raw/                    cached CSV files from each source
    processed/              intermediate analysis outputs
  powerbi/
    POWERBI_SETUP.md        step-by-step guide for Power BI setup
```

---

## Power BI setup

Open `powerbi/POWERBI_SETUP.md` for full instructions including:

- How to connect Power BI to the Excel file
- Table relationships to create in the model view
- DAX measures for KPI cards
- Recommended layout for each of the 8 report pages

---

## AI features

| Feature | Method | Output |
|---------|--------|--------|
| Forecasting | ARIMA (auto order) | 8-period forecasts with 80% and 95% confidence intervals |
| Anomaly detection | Isolation Forest | Flagged quarters with primary driver label |
| Economic regime | Rule-based classifier | 6 labels: Expansion, Moderate Growth, Recovery, Stagflation, Contraction, Crisis |
| Health score | Weighted component scoring | 0 to 100 composite score per quarter |
| Narrative insights | Claude API (claude-sonnet-4-6) | 10 to 14 analyst-style insights grounded in real data values |

If the Anthropic API key is not set, the pipeline falls back to template-based insights and all other features still run normally.

---

## Re-running to get fresh data

Run `python run_pipeline.py` at any time to pull the latest data and regenerate the Excel file. Then click Refresh in Power BI to update the report.
