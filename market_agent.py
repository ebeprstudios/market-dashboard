"""
market_agent.py
EBEPR Studios — Daily Portfolio Watch Clock
Runs every weekday at 8:30 AM ET via GitHub Actions
Fetches live prices → Claude analysis → Email briefing to Erica
"""

import os
import json
import smtplib
import requests
from datetime import datetime, date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# ── SECRETS FROM GITHUB ───────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
EMAIL_FROM        = os.environ.get("EMAIL_FROM", "")
EMAIL_PASSWORD    = os.environ.get("EMAIL_PASSWORD", "")
MANAGER_EMAIL     = os.environ.get("MANAGER_EMAIL", "")
HARDCODED_CC      = "ebeprinc@gmail.com"

# ── PORTFOLIO ─────────────────────────────────────────────────────
PORTFOLIO = {
    "tier1": [
        {"symbol": "SPY",  "name": "S&P 500",               "qty": 7.06,   "cb": 620.21},
        {"symbol": "QQQ",  "name": "Nasdaq-100",             "qty": 6.817,  "cb": 600.68},
        {"symbol": "VGT",  "name": "Vanguard Info Tech",     "qty": 41.144, "cb": 94.47},
        {"symbol": "DIA",  "name": "Dow Jones",              "qty": 5.077,  "cb": 414.27},
        {"symbol": "IWM",  "name": "Russell 2000",           "qty": 4.052,  "cb": 203.99},
        {"symbol": "SCHD", "name": "Schwab US Dividend",     "qty": 37.46,  "cb": 29.94},
        {"symbol": "XLK",  "name": "Tech Select Sector",     "qty": 4.048,  "cb": 111.41},
        {"symbol": "QTUM", "name": "Defiance Quantum",       "qty": 4,      "cb": 160.09, "path_b": True},
    ],
    "tier2": [
        {"symbol": "NLR",  "name": "VanEck Uranium Nuclear", "qty": 29,     "cb": 137.00, "stop": "trailing $3"},
        {"symbol": "GLD",  "name": "SPDR Gold",              "qty": 5,      "cb": 432.83},
        {"symbol": "GDX",  "name": "VanEck Gold Miners",     "qty": 5,      "cb": 105.49, "flag": "REVIEW — sell pending"},
        {"symbol": "SLV",  "name": "iShares Silver",         "qty": 10,     "cb": 84.79},
        {"symbol": "BLOK", "name": "Amplify Blockchain",     "qty": 9.036,  "cb": 52.90},
        {"symbol": "SHOC", "name": "Strive US Semiconductor","qty": 2.001,  "cb": 78.25},
        {"symbol": "IDGT", "name": "iShares US Digital Infra","qty": 5,     "cb": 91.83},
        {"symbol": "XLI",  "name": "Industrials Select",     "qty": 5.014,  "cb": 174.93},
        {"symbol": "XLU",  "name": "Utilities (AI Power)",   "qty": 6.041,  "cb": 46.97},
        {"symbol": "XLF",  "name": "Financials Select",      "qty": 0.015,  "cb": 48.87},
        {"symbol": "XLP",  "name": "Consumer Staples",       "qty": 2.011,  "cb": 84.30},
    ],
    "cash": 9672.17,
}

INVESTMENT_RULES = """
INVESTMENT RULES — NON-NEGOTIABLE:

TIER SYSTEM:
- Tier 1 (SPY, QQQ, VGT, DIA, IWM, SCHD, XLK, QTUM) = UNTOUCHABLE. Never sell. Add from cash only on confirmed dips.
- Tier 2 = Trim freely when thesis ends. Cash funds new buys — never Tier 1 proceeds.

FALLING KNIFE RULE:
- Never buy if price is below all 4 MAs. Check: MAs, MACD, days fallen, bottom pivot before entry.
- Below all 4 MAs = FALLING KNIFE — stay out.
- Below 9/13/20-day but above 50-day = CAUTION zone.
- Above all 4 MAs = STRONG BULL.

BOTTOM PIVOT RULE:
- Never buy at "the low." Only enter after confirmed reversal candle (hammer, engulfing green, long lower wick) on above-average volume + higher lows following.

MA COLORS:
- 9-day = Yellow | 13-day = Blue | 20-day = White | 50-day = Red
- Ideal buy = price bouncing UP through white 20-day with red 50-day as support below.

TRIPLE WITCHING:
- 3rd Friday of Mar/Jun/Sep/Dec = widen stops to $2-3. No new entries that week.
- June 2026 Triple Witching = June 18, 2026.

RATE HIKE RISK (June 2026):
- Fed hike probability ~49-57%. Most positions are rate-sensitive (tech, metals, utilities, small caps).
- If hike: lean into XLF, DIA, SCHD, XLI, cash. Delay tech and metals adds.

PORTFOLIO GAPS:
- Memory layer (SMH/SOXX/MU) = UNFILLED. Highest AI infrastructure priority.
- Defense sleeve (ITA/XAR) = UNFILLED.
- RACK (data center supply chain, launched June 2, 2026) = watch for liquidity.

PENDING DECISIONS:
- GDX: sell — no conviction, -24.84%, redundant with GLD
- NLR stop: $3 trailing — may need widening
- SLV/GLD adds: only on confirmed bottom pivot — not catching falling knives
- XLF: reconsider selling — benefits from rate hike environment
- CASH: 30% is correct posture in hawkish regime. Deploy in thirds only.
"""

# ── FETCH LIVE PRICES ─────────────────────────────────────────────
def fetch_prices(symbols: list) -> dict:
    """Fetch current prices via yfinance."""
    prices = {}
    try:
        import yfinance as yf
        tickers = yf.Tickers(" ".join(symbols))
        for sym in symbols:
            try:
                ticker = tickers.tickers[sym]
                info   = ticker.fast_info
                price  = getattr(info, "last_price", None) or getattr(info, "previous_close", None)
                prev   = getattr(info, "previous_close", None)
                prices[sym] = {
                    "price": round(float(price), 2) if price else None,
                    "prev":  round(float(prev), 2)  if prev  else None,
                    "change_pct": round(((float(price) - float(prev)) / float(prev)) * 100, 2) if price and prev else None,
                }
            except Exception as e:
                print(f"Price fetch error for {sym}: {e}")
                prices[sym] = {"price": None, "prev": None, "change_pct": None}
    except ImportError:
        print("yfinance not installed — prices unavailable")
        for sym in symbols:
            prices[sym] = {"price": None, "prev": None, "change_pct": None}
    return prices


def build_price_summary(prices: dict) -> str:
    lines = []
    for sym, data in prices.items():
        if data["price"]:
            chg = f"{data['change_pct']:+.2f}%" if data["change_pct"] is not None else "N/A"
            lines.append(f"{sym}: ${data['price']} ({chg})")
        else:
            lines.append(f"{sym}: price unavailable")
    return "\n".join(lines)


# ── RUN CLAUDE ANALYSIS ───────────────────────────────────────────
def run_claude_analysis(prices: dict) -> dict:
    all_positions = []
    for p in PORTFOLIO["tier1"]:
        price_data = prices.get(p["symbol"], {})
        price      = price_data.get("price")
        pct        = price_data.get("change_pct")
        gl_pct     = round(((price - p["cb"]) / p["cb"]) * 100, 2) if price else None
        all_positions.append(
            f"{p['symbol']} ({p['name']}) — Tier 1{'B' if p.get('path_b') else ''} — "
            f"{p['qty']} shares @ CB ${p['cb']} — "
            f"Current: ${price or 'N/A'} ({f'{pct:+.2f}%' if pct is not None else 'N/A'} today) — "
            f"Total G/L: {f'{gl_pct:+.1f}%' if gl_pct is not None else 'N/A'}"
        )
    for p in PORTFOLIO["tier2"]:
        price_data = prices.get(p["symbol"], {})
        price      = price_data.get("price")
        pct        = price_data.get("change_pct")
        gl_pct     = round(((price - p["cb"]) / p["cb"]) * 100, 2) if price else None
        flag       = f" — FLAG: {p['flag']}" if p.get("flag") else ""
        stop       = f" — Stop: {p['stop']}" if p.get("stop") else ""
        all_positions.append(
            f"{p['symbol']} ({p['name']}) — Tier 2 — "
            f"{p['qty']} shares @ CB ${p['cb']} — "
            f"Current: ${price or 'N/A'} ({f'{pct:+.2f}%' if pct is not None else 'N/A'} today) — "
            f"Total G/L: {f'{gl_pct:+.1f}%' if gl_pct is not None else 'N/A'}"
            f"{stop}{flag}"
        )

    today_str = datetime.now().strftime("%A, %B %-d, %Y")
    price_summary = build_price_summary(prices)

    # Check Triple Witching proximity
    tw_dates_2026 = [date(2026, 3, 20), date(2026, 6, 18), date(2026, 9, 18), date(2026, 12, 18)]
    days_to_tw    = min((abs((tw - date.today()).days) for tw in tw_dates_2026), default=999)
    tw_alert      = days_to_tw <= 5

    prompt = f"""You are a disciplined investment advisor running the daily portfolio watch clock for Erica Ehiwe's Fidelity 401k BrokerageLink account.

DATE: {today_str}
TRIPLE WITCHING ALERT: {'YES — within {days_to_tw} days of June 18' if tw_alert else 'No'}

LIVE PRICES TODAY:
{price_summary}

PORTFOLIO POSITIONS:
{chr(10).join(all_positions)}

CASH: ${PORTFOLIO['cash']:,.2f} (30.07% of account)

{INVESTMENT_RULES}

Run the daily portfolio briefing. Apply every rule to every position. Output ONLY valid JSON — no markdown, no backticks.

{{
  "date": "{today_str}",
  "market_pulse": "2-3 sentences on what the macro is doing today and what matters most",
  "regime": "HAWKISH or NEUTRAL or DOVISH",
  "regime_note": "one line",
  "triple_witching_alert": {str(tw_alert).lower()},
  "days_to_tw": {days_to_tw},
  "account_health": "STRONG or CAUTION or RISK",
  "health_note": "one line",
  "daily_focus": "the single most important thing to watch or do today — one sentence",
  "master_action_list": [
    {{
      "rank": 1,
      "symbol": "TICKER",
      "action": "SELL or ADD or HOLD or WATCH or AVOID",
      "urgency": "HIGH or MEDIUM or LOW",
      "reason": "one line broker note",
      "condition": "Execute today or Wait for pivot or Watch closely"
    }}
  ],
  "positions": [
    {{
      "symbol": "SPY",
      "tier": "1",
      "action": "HOLD or ADD or SELL or WATCH or AVOID",
      "urgency": "HIGH or MEDIUM or LOW or NONE",
      "signal": "one line — what price action is saying",
      "rule_check": "e.g. Falling Knife: CLEAR or Bottom Pivot: NOT CONFIRMED",
      "note": "1-2 sentence broker note"
    }}
  ],
  "cash_strategy": "2-3 sentences on how to manage the $9,672 today",
  "watch_list": ["SMH", "ITA", "RACK"],
  "risk_flags": ["list any rule violations or urgent risks detected today"]
}}"""

    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key":         ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type":      "application/json",
        },
        json={
            "model":      "claude-sonnet-4-6",
            "max_tokens": 4000,
            "messages":   [{"role": "user", "content": prompt}],
        },
        timeout=60,
    )
    response.raise_for_status()
    raw   = response.json()["content"][0]["text"].strip()
    clean = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(clean)


# ── BUILD EMAIL HTML ──────────────────────────────────────────────
def action_color(action: str) -> str:
    return {
        "SELL": "#f87171", "ADD": "#60a5fa", "HOLD": "#4ade80",
        "WATCH": "#fbbf24", "AVOID": "#ef4444",
    }.get(action, "#94a3b8")


def urgency_label(urgency: str) -> str:
    colors = {"HIGH": "#f87171", "MEDIUM": "#fbbf24", "LOW": "#4ade80", "NONE": "#475569"}
    return f'<span style="font-size:9px;font-weight:700;color:{colors.get(urgency,"#94a3b8")};padding:2px 8px;border:1px solid {colors.get(urgency,"#94a3b8")}33;border-radius:3px;letter-spacing:1px;">{urgency}</span>'


def build_email_html(report: dict, prices: dict) -> str:
    today_str    = report.get("date", datetime.now().strftime("%A, %B %-d, %Y"))
    regime       = report.get("regime", "NEUTRAL")
    regime_color = {"HAWKISH": "#f87171", "NEUTRAL": "#fbbf24", "DOVISH": "#4ade80"}.get(regime, "#94a3b8")
    health       = report.get("account_health", "CAUTION")
    health_color = {"STRONG": "#4ade80", "CAUTION": "#fbbf24", "RISK": "#f87171"}.get(health, "#94a3b8")
    tw_alert     = report.get("triple_witching_alert", False)
    days_to_tw   = report.get("days_to_tw", 999)

    # Build master action list
    action_rows = ""
    for item in report.get("master_action_list", []):
        ac = action_color(item.get("action", "HOLD"))
        action_rows += f"""
<tr>
  <td style="padding:10px 12px;font-size:11px;color:#94a3b8;font-family:'Courier New',monospace;border-bottom:1px solid #1e2d45;">#{item.get('rank','')}</td>
  <td style="padding:10px 12px;font-size:14px;font-weight:700;color:#e2e8f0;font-family:'Courier New',monospace;border-bottom:1px solid #1e2d45;">{item.get('symbol','')}</td>
  <td style="padding:10px 12px;border-bottom:1px solid #1e2d45;">
    <span style="font-size:10px;font-weight:900;color:{ac};background:{ac}18;border:1px solid {ac}33;padding:2px 8px;border-radius:3px;letter-spacing:1px;font-family:'Courier New',monospace;">{item.get('action','')}</span>
  </td>
  <td style="padding:10px 12px;font-size:11px;color:#94a3b8;font-family:'Courier New',monospace;border-bottom:1px solid #1e2d45;">{item.get('reason','')}</td>
  <td style="padding:10px 12px;font-size:10px;color:#475569;font-family:'Courier New',monospace;border-bottom:1px solid #1e2d45;">{item.get('condition','')}</td>
</tr>"""

    # Build position rows
    tier1_rows = ""
    tier2_rows = ""
    for pos in report.get("positions", []):
        sym   = pos.get("symbol", "")
        tier  = pos.get("tier", "2")
        ac    = action_color(pos.get("action", "HOLD"))
        pd    = prices.get(sym, {})
        price = pd.get("price")
        pct   = pd.get("change_pct")
        pct_color = "#4ade80" if (pct or 0) >= 0 else "#f87171"
        price_str = f"${price}" if price else "N/A"
        pct_str   = f"{pct:+.2f}%" if pct is not None else "N/A"

        row = f"""
<tr>
  <td style="padding:10px 12px;font-size:13px;font-weight:700;color:#e2e8f0;font-family:'Courier New',monospace;border-bottom:1px solid #1a2535;">{sym}</td>
  <td style="padding:10px 12px;font-size:12px;color:#475569;font-family:'Courier New',monospace;border-bottom:1px solid #1a2535;">{price_str}</td>
  <td style="padding:10px 12px;font-size:12px;color:{pct_color};font-family:'Courier New',monospace;border-bottom:1px solid #1a2535;">{pct_str}</td>
  <td style="padding:10px 12px;border-bottom:1px solid #1a2535;">
    <span style="font-size:10px;font-weight:900;color:{ac};background:{ac}18;border:1px solid {ac}33;padding:2px 8px;border-radius:3px;letter-spacing:1px;font-family:'Courier New',monospace;">{pos.get('action','')}</span>
  </td>
  <td style="padding:10px 12px;font-size:10px;color:#64748b;font-family:'Courier New',monospace;border-bottom:1px solid #1a2535;">{pos.get('signal','')}</td>
</tr>"""
        if tier == "1":
            tier1_rows += row
        else:
            tier2_rows += row

    # Risk flags
    risk_html = ""
    for flag in report.get("risk_flags", []):
        risk_html += f'<div style="padding:8px 12px;margin-bottom:6px;background:rgba(248,113,113,0.08);border-left:2px solid #f87171;font-size:11px;color:#fca5a5;font-family:\'Courier New\',monospace;">⚠ {flag}</div>'

    # Watch list
    watch_html = "".join([
        f'<span style="display:inline-block;margin-right:8px;font-size:10px;font-weight:700;color:#fbbf24;background:rgba(251,191,36,0.1);border:1px solid rgba(251,191,36,0.3);padding:3px 10px;border-radius:3px;font-family:\'Courier New\',monospace;">{sym}</span>'
        for sym in report.get("watch_list", [])
    ])

    # Triple witching banner
    tw_banner = ""
    if tw_alert:
        tw_banner = f"""
<tr><td>
  <div style="background:rgba(248,113,113,0.1);border:1px solid #f87171;border-radius:6px;padding:14px 20px;margin-bottom:16px;text-align:center;">
    <div style="font-size:11px;font-weight:900;color:#f87171;letter-spacing:3px;text-transform:uppercase;font-family:'Courier New',monospace;">⚠ TRIPLE WITCHING IN {days_to_tw} DAYS — JUNE 18, 2026</div>
    <div style="font-size:10px;color:#fca5a5;margin-top:6px;font-family:'Courier New',monospace;">Widen all stops to $2–3. No new entries this week. Protect cash.</div>
  </div>
</td></tr>"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#050a12;font-family:'Courier New',monospace;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#050a12;">
<tr><td align="center" style="padding:20px 12px 40px;">
<table width="640" cellpadding="0" cellspacing="0" style="max-width:640px;width:100%;">

<!-- HEADER -->
<tr><td style="background:#080e1a;border-radius:8px 8px 0 0;padding:20px 24px;border-bottom:2px solid #38bdf8;">
  <table width="100%" cellpadding="0" cellspacing="0"><tr>
    <td>
      <div style="font-size:9px;font-weight:700;color:#38bdf8;letter-spacing:4px;text-transform:uppercase;margin-bottom:4px;">⌚ PORTFOLIO WATCH CLOCK</div>
      <div style="font-size:18px;font-weight:700;color:#e2e8f0;">Daily Briefing</div>
      <div style="font-size:10px;color:#475569;margin-top:3px;">{today_str}</div>
    </td>
    <td align="right" valign="top">
      <table cellpadding="0" cellspacing="0"><tr>
        <td style="text-align:center;padding:0 16px;">
          <div style="font-size:9px;color:#475569;letter-spacing:2px;margin-bottom:4px;">REGIME</div>
          <div style="font-size:13px;font-weight:900;color:{regime_color};">{regime}</div>
        </td>
        <td style="text-align:center;padding:0 16px;">
          <div style="font-size:9px;color:#475569;letter-spacing:2px;margin-bottom:4px;">HEALTH</div>
          <div style="font-size:13px;font-weight:900;color:{health_color};">{health}</div>
        </td>
      </tr></table>
    </td>
  </tr></table>
</td></tr>

<!-- GOLD STRIPE -->
<tr><td style="height:2px;background:linear-gradient(90deg,#38bdf8,#0ea5e9,#38bdf8);"></td></tr>

<tr><td style="background:#080e1a;padding:20px 24px;border-left:1px solid #1e2d45;border-right:1px solid #1e2d45;">

  <!-- TW BANNER -->
  <table width="100%" cellpadding="0" cellspacing="0">{tw_banner}</table>

  <!-- MARKET PULSE -->
  <div style="font-size:9px;font-weight:700;color:#38bdf8;letter-spacing:3px;text-transform:uppercase;margin-bottom:8px;">MARKET PULSE</div>
  <div style="font-size:12px;color:#cbd5e1;line-height:1.8;margin-bottom:20px;padding:12px 16px;background:#0a1628;border-radius:5px;border-left:2px solid #38bdf8;">{report.get('market_pulse','')}</div>

  <!-- DAILY FOCUS -->
  <div style="font-size:9px;font-weight:700;color:#fbbf24;letter-spacing:3px;text-transform:uppercase;margin-bottom:8px;">TODAY'S FOCUS</div>
  <div style="font-size:13px;font-weight:700;color:#fbbf24;margin-bottom:20px;padding:12px 16px;background:rgba(251,191,36,0.06);border-radius:5px;border-left:2px solid #fbbf24;">{report.get('daily_focus','')}</div>

  <!-- RISK FLAGS -->
  {f'<div style="font-size:9px;font-weight:700;color:#f87171;letter-spacing:3px;text-transform:uppercase;margin-bottom:8px;">RISK FLAGS</div>{risk_html}<div style="margin-bottom:20px;"></div>' if risk_html else ''}

  <!-- MASTER ACTION LIST -->
  <div style="font-size:9px;font-weight:700;color:#e2e8f0;letter-spacing:3px;text-transform:uppercase;margin-bottom:10px;">MASTER ACTION LIST — RANKED BY URGENCY</div>
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0a1628;border-radius:5px;overflow:hidden;margin-bottom:20px;">
    <tr style="background:#0d1e36;">
      <td style="padding:8px 12px;font-size:9px;color:#475569;letter-spacing:2px;">#</td>
      <td style="padding:8px 12px;font-size:9px;color:#475569;letter-spacing:2px;">SYMBOL</td>
      <td style="padding:8px 12px;font-size:9px;color:#475569;letter-spacing:2px;">ACTION</td>
      <td style="padding:8px 12px;font-size:9px;color:#475569;letter-spacing:2px;">REASON</td>
      <td style="padding:8px 12px;font-size:9px;color:#475569;letter-spacing:2px;">CONDITION</td>
    </tr>
    {action_rows}
  </table>

  <!-- TIER 1 POSITIONS -->
  <div style="font-size:9px;font-weight:700;color:#38bdf8;letter-spacing:3px;text-transform:uppercase;margin-bottom:10px;">TIER 1 — FOREVER HOLDS</div>
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0a1628;border-radius:5px;overflow:hidden;margin-bottom:20px;">
    <tr style="background:#0d1e36;">
      <td style="padding:8px 12px;font-size:9px;color:#475569;letter-spacing:2px;">SYMBOL</td>
      <td style="padding:8px 12px;font-size:9px;color:#475569;letter-spacing:2px;">PRICE</td>
      <td style="padding:8px 12px;font-size:9px;color:#475569;letter-spacing:2px;">TODAY</td>
      <td style="padding:8px 12px;font-size:9px;color:#475569;letter-spacing:2px;">ACTION</td>
      <td style="padding:8px 12px;font-size:9px;color:#475569;letter-spacing:2px;">SIGNAL</td>
    </tr>
    {tier1_rows}
  </table>

  <!-- TIER 2 POSITIONS -->
  <div style="font-size:9px;font-weight:700;color:#7c3aed;letter-spacing:3px;text-transform:uppercase;margin-bottom:10px;">TIER 2 — ACTIVE POSITIONS</div>
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0a1628;border-radius:5px;overflow:hidden;margin-bottom:20px;">
    <tr style="background:#0d1e36;">
      <td style="padding:8px 12px;font-size:9px;color:#475569;letter-spacing:2px;">SYMBOL</td>
      <td style="padding:8px 12px;font-size:9px;color:#475569;letter-spacing:2px;">PRICE</td>
      <td style="padding:8px 12px;font-size:9px;color:#475569;letter-spacing:2px;">TODAY</td>
      <td style="padding:8px 12px;font-size:9px;color:#475569;letter-spacing:2px;">ACTION</td>
      <td style="padding:8px 12px;font-size:9px;color:#475569;letter-spacing:2px;">SIGNAL</td>
    </tr>
    {tier2_rows}
  </table>

  <!-- CASH STRATEGY -->
  <div style="font-size:9px;font-weight:700;color:#4ade80;letter-spacing:3px;text-transform:uppercase;margin-bottom:8px;">CASH STRATEGY — $9,672.17</div>
  <div style="font-size:12px;color:#94a3b8;line-height:1.8;margin-bottom:20px;padding:12px 16px;background:#0a1628;border-radius:5px;border-left:2px solid #4ade80;">{report.get('cash_strategy','')}</div>

  <!-- WATCH LIST -->
  <div style="font-size:9px;font-weight:700;color:#fbbf24;letter-spacing:3px;text-transform:uppercase;margin-bottom:8px;">WATCH LIST</div>
  <div style="margin-bottom:8px;">{watch_html}</div>

</td></tr>

<!-- FOOTER -->
<tr><td style="background:#050a12;border-radius:0 0 8px 8px;padding:14px 24px;text-align:center;border:1px solid #1e2d45;border-top:none;">
  <div style="font-size:9px;color:#334155;letter-spacing:2px;text-transform:uppercase;">EBEPR STUDIOS · PORTFOLIO WATCH CLOCK · NOT FINANCIAL ADVICE</div>
</td></tr>

</table>
</td></tr>
</table>
</body></html>"""


# ── SEND EMAIL ────────────────────────────────────────────────────
def send_email(html: str, subject: str):
    recipient = MANAGER_EMAIL.strip().replace("\n", "").replace("\r", "")
    cc        = HARDCODED_CC

    msg             = MIMEMultipart("alternative")
    msg["Subject"]  = subject
    msg["From"]     = EMAIL_FROM
    msg["To"]       = recipient
    msg["Cc"]       = cc
    msg.attach(MIMEText(html, "html"))

    all_to = list(set([recipient, cc]))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(EMAIL_FROM, EMAIL_PASSWORD)
        s.sendmail(EMAIL_FROM, all_to, msg.as_string())
    print(f"Briefing sent to {recipient} (CC: {cc})")


# ── MAIN ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"Portfolio Watch Clock — {datetime.now().strftime('%Y-%m-%d %H:%M:%S ET')}")

    # All symbols to fetch
    all_symbols = [p["symbol"] for p in PORTFOLIO["tier1"]] + \
                  [p["symbol"] for p in PORTFOLIO["tier2"]]

    print(f"Fetching prices for {len(all_symbols)} positions...")
    prices = fetch_prices(all_symbols)

    for sym, data in prices.items():
        if data["price"]:
            print(f"  {sym}: ${data['price']} ({data['change_pct']:+.2f}%)")
        else:
            print(f"  {sym}: price unavailable")

    print("Running Claude analysis...")
    report = run_claude_analysis(prices)
    print(f"Regime: {report.get('regime')} | Health: {report.get('account_health')}")
    print(f"Action items: {len(report.get('master_action_list', []))}")

    print("Building email...")
    html    = build_email_html(report, prices)
    today   = datetime.now().strftime("%b %-d")
    regime  = report.get("regime", "")
    health  = report.get("account_health", "")
    subject = f"⌚ Watch Clock — {today} | {regime} | {health} | {len(report.get('master_action_list',[]))} Actions"

    print("Sending briefing...")
    send_email(html, subject)
    print("Done.")
