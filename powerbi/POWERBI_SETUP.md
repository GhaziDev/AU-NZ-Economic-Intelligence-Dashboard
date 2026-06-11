# AU/NZ Economic Intelligence Dashboard — Power BI Setup Guide

## Step 1: Connect to the Data Source

1. Open **Power BI Desktop**
2. Click **Home → Get Data → Excel Workbook**
3. Navigate to `output/AU_NZ_Economic_Intelligence.xlsx`
4. In the Navigator, select **all 15 sheets** (Ctrl+A) and click **Load**

---

## Step 2: Set Up Relationships

In the **Model View** (Relationship icon in left sidebar):

| From Table             | From Column | To Table        | To Column |
|------------------------|-------------|-----------------|-----------|
| 01_AU_Cash_Rate        | Date        | 15_Date_Table   | Date      |
| 02_AU_CPI              | Date        | 15_Date_Table   | Date      |
| 03_AU_GDP              | Date        | 15_Date_Table   | Date      |
| 04_AU_Labour           | Date        | 15_Date_Table   | Date      |
| 05_AU_Housing_Rates    | Date        | 15_Date_Table   | Date      |
| 09_AI_Forecasts        | Forecast_Date | 15_Date_Table | Date      |
| 10_Economic_Regimes    | Quarter     | 15_Date_Table   | Date      |
| 11_Health_Score        | Quarter     | 15_Date_Table   | Date      |
| 12_Anomalies           | Quarter     | 15_Date_Table   | Date      |

---

## Step 3: Create Key DAX Measures

Create a new empty table called `_Measures` and add these:

### Core Metrics
```dax
Latest Cash Rate =
VAR MaxDate = MAX('01_AU_Cash_Rate'[Date])
RETURN CALCULATE(MAX('01_AU_Cash_Rate'[CashRate_Pct]), '01_AU_Cash_Rate'[Date] = MaxDate)
```

```dax
Latest CPI YoY =
VAR MaxDate = MAX('02_AU_CPI'[Date])
RETURN CALCULATE(MAX('02_AU_CPI'[CPI_YoY_Pct]), '02_AU_CPI'[Date] = MaxDate)
```

```dax
Latest Unemployment =
VAR MaxDate = MAX('04_AU_Labour'[Date])
RETURN CALCULATE(MAX('04_AU_Labour'[Unemployment_Rate_Pct]), '04_AU_Labour'[Date] = MaxDate)
```

```dax
Latest Health Score =
VAR MaxQtr = MAX('11_Health_Score'[Quarter])
RETURN CALCULATE(MAX('11_Health_Score'[Health_Score]), '11_Health_Score'[Quarter] = MaxQtr)
```

```dax
Latest GDP Growth =
VAR MaxDate = MAX('03_AU_GDP'[Date])
RETURN CALCULATE(
    MAX('03_AU_GDP'[GDP_Growth_YoY_Pct]),
    '03_AU_GDP'[Date] = MaxDate
)
```

### YoY Changes
```dax
Cash Rate YoY Change =
VAR CurrentDate = MAX('01_AU_Cash_Rate'[Date])
VAR PriorYearDate = EDATE(CurrentDate, -12)
VAR CurrentRate = CALCULATE(MAX('01_AU_Cash_Rate'[CashRate_Pct]), '01_AU_Cash_Rate'[Date] = CurrentDate)
VAR PriorRate = CALCULATE(MAX('01_AU_Cash_Rate'[CashRate_Pct]), '01_AU_Cash_Rate'[Date] <= PriorYearDate,
    TOPN(1, FILTER('01_AU_Cash_Rate', '01_AU_Cash_Rate'[Date] <= PriorYearDate), '01_AU_Cash_Rate'[Date], DESC))
RETURN CurrentRate - PriorRate
```

```dax
Unemployment Direction =
VAR Chg = [Cash Rate YoY Change]
RETURN IF(Chg > 0, "Rising", IF(Chg < 0, "Falling", "Stable"))
```

### Mortgage Spread
```dax
Mortgage Spread bps =
VAR Rate = CALCULATE(
    MAX('05_AU_Housing_Rates'[OO_Outstanding_All_Pct]),
    TOPN(1, '05_AU_Housing_Rates', '05_AU_Housing_Rates'[Date], DESC)
)
VAR Cash = [Latest Cash Rate]
RETURN (Rate - Cash) * 100
```

### Economic Health Status
```dax
Health Status Icon =
VAR Score = [Latest Health Score]
RETURN
    SWITCH(
        TRUE(),
        Score >= 80, "Excellent",
        Score >= 65, "Good",
        Score >= 50, "Average",
        Score >= 30, "Below Average",
        "Poor"
    )
```

### AU vs NZ Comparison
```dax
AU GDP Growth Latest =
CALCULATE(
    LASTNONBLANK('06_WB_AU_Annual'[gdp_growth], 1),
    ALL('06_WB_AU_Annual')
)

NZ GDP Growth Latest =
CALCULATE(
    LASTNONBLANK('07_WB_NZ_Annual'[gdp_growth], 1),
    ALL('07_WB_NZ_Annual')
)
```

---

## Step 4: Recommended Visuals

### Page 1: Executive Overview
| Visual               | Fields / Config                                                                 |
|----------------------|---------------------------------------------------------------------------------|
| KPI Card             | `Latest Cash Rate` / Target: 2.5 (RBA neutral rate)                            |
| KPI Card             | `Latest CPI YoY` / Target: 2.5 (mid-point)                                     |
| KPI Card             | `Latest Unemployment` / Target: 4.5                                             |
| KPI Card             | `Latest Health Score` / Format: 0 decimal places                                |
| Line Chart           | X: Date, Y: CashRate_Pct — table: 01_AU_Cash_Rate (1990–present)               |
| Clustered Bar        | X: Year, Y: gdp_growth — tables: WB_AU and WB_NZ (use Country legend)          |

### Page 2: Inflation & Rates
| Visual               | Fields                                                                          |
|----------------------|---------------------------------------------------------------------------------|
| Line Chart (dual)    | X: Date, Y1: CPI_YoY_Pct (02), Y2: CashRate_Pct (01)                          |
| Reference Line       | Add constant line at Y=2 and Y=3 (RBA target band)                             |
| Area Chart           | X: Date, Y: OO_Outstanding_All_Pct (05) — housing mortgage rate                |

### Page 3: AI Forecasts
| Visual               | Fields                                                                          |
|----------------------|---------------------------------------------------------------------------------|
| Line Chart           | X: Forecast_Date, Y: Forecast_Value — filter by Series slicer                  |
| Error bars / shading | Add CI95_Lower, CI95_Upper as error bars (or separate lines)                    |
| Slicer               | Series column from 09_AI_Forecasts (multi-select)                              |
| Table                | Show Forecast_Date, Forecast_Value, CI80_Lower, CI80_Upper, Model              |

### Page 4: Economic Health & Regimes
| Visual               | Fields                                                                          |
|----------------------|---------------------------------------------------------------------------------|
| Gauge                | Value: `Latest Health Score`, Min: 0, Max: 100, Target: 75                     |
| Timeline             | X: Quarter, Y: Health_Score (11) — line chart                                  |
| Matrix/Table         | Quarter, Regime, Regime_Score — from 10_Economic_Regimes                       |
| Conditional Formatting | Regime column: Red=Crisis/Contraction, Yellow=Stagflation, Green=Expansion    |

### Page 5: Anomaly Detection
| Visual               | Fields                                                                          |
|----------------------|---------------------------------------------------------------------------------|
| Scatter Plot         | X: GDP_Growth, Y: CPI_YoY, Size: Unemployment, Color: Anomaly_Flag (12)        |
| Table (filtered)     | Show only rows where Anomaly_Flag = 1 — include Primary_Driver column          |
| Line Chart           | X: Quarter, Y: Unemployment_Rate_Pct — highlight anomaly dates                 |

### Page 6: AU vs NZ Comparison
| Visual               | Fields                                                                          |
|----------------------|---------------------------------------------------------------------------------|
| Line Chart           | X: Year, Y: CPI_Inflation_Pct — legend: Country (08_AU_NZ_Comparison)         |
| Line Chart           | X: Year, Y: Unemployment_Pct — legend: Country                                 |
| Bar Chart            | X: Year, Y: GDP_Billion_USD — two series for AU and NZ                         |
| Card                 | `AU GDP Growth Latest` and `NZ GDP Growth Latest`                              |

### Page 7: Correlations
| Visual               | Fields                                                                          |
|----------------------|---------------------------------------------------------------------------------|
| Matrix Table         | All columns from 13_Correlations with conditional formatting (green=+1, red=-1)|
| Bar Chart (sorted)   | X: Indicator, Y: correlation value vs chosen indicator                          |

### Page 8: AI Insights
| Visual               | Fields                                                                          |
|----------------------|---------------------------------------------------------------------------------|
| Table                | Category, Insight, Significance — from 14_AI_Insights                         |
| Conditional Format   | Significance: High = red, Medium = yellow                                      |

---

## Step 5: Enable Q&A (Natural Language)

1. Go to **File → Options → Preview Features → Enable Q&A**
2. In a report page, add the **Q&A visual**
3. Example questions to try:
   - "What is the current cash rate?"
   - "Show unemployment trend since 2020"
   - "Compare AU and NZ GDP growth"
   - "Which quarters had anomalies?"
   - "What is the economic health score?"

---

## Step 6: Refresh Setup

To keep data current:
1. Run `python run_pipeline.py` to regenerate the Excel file (takes ~20 seconds)
2. In Power BI, click **Refresh** on the dataset
3. For automated refresh: set up a **scheduled refresh** in Power BI Service after publishing

---

## Data Sources

| Source | URL | Update Frequency |
|--------|-----|-----------------|
| RBA Cash Rate | rba.gov.au (F1) | Monthly |
| RBA CPI | rba.gov.au (G1) | Quarterly |
| RBA GDP | rba.gov.au (H1) | Quarterly |
| RBA Labour Force | rba.gov.au (H5) | Monthly |
| RBA Housing Rates | rba.gov.au (F6) | Monthly |
| World Bank AU/NZ | api.worldbank.org | Annual |

---

## AI Model Details

| Analysis | Algorithm | Input Features | Output |
|----------|-----------|----------------|--------|
| Forecasting | ARIMA (auto-order) | Single time series (2000-present) | 8-period point forecast + 80%/95% CI |
| Anomaly Detection | Isolation Forest (contamination=7%) | GDP Growth, CPI, Unemployment, Cash Rate | Anomaly flag + primary driver |
| Economic Regime | Rule-based classifier | GDP Growth, CPI, Unemployment, trend | 6 regime labels |
| Health Score | Weighted component scoring | 5 indicators | 0–100 composite score |
