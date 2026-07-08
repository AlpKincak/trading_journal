"""Plotly chart builders for the dashboard.

Pure functions: each takes a DataFrame and returns a Plotly ``Figure`` (or None
when there is nothing to plot). Backgrounds are transparent so charts blend with
either a light or dark Streamlit theme.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

PROFIT_COLOR = "#26a69a"
LOSS_COLOR = "#ef5350"
ACCENT_COLOR = "#4c8bf5"
GRID_COLOR = "rgba(128,128,128,0.20)"


def _style(fig: go.Figure, height: int = 320) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=10, r=10, t=40, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_xaxes(gridcolor=GRID_COLOR, zeroline=False)
    fig.update_yaxes(gridcolor=GRID_COLOR, zeroline=True, zerolinecolor=GRID_COLOR)
    return fig


def daily_pnl_bar(daily: pd.DataFrame) -> go.Figure | None:
    """Bar chart of net P&L per trading day (green up / red down)."""
    if daily is None or daily.empty:
        return None
    colors = [PROFIT_COLOR if v >= 0 else LOSS_COLOR for v in daily["net_pnl"]]
    fig = go.Figure(
        go.Bar(
            x=daily["date"],
            y=daily["net_pnl"],
            marker_color=colors,
            hovertemplate="%{x|%Y-%m-%d}<br>Net P&L: %{y:$,.2f}<extra></extra>",
        )
    )
    fig.update_layout(title="Net daily P&L")
    return _style(fig)


def cumulative_pnl_line(daily: pd.DataFrame) -> go.Figure | None:
    """Line/area chart of cumulative daily net P&L."""
    if daily is None or daily.empty:
        return None
    fig = go.Figure(
        go.Scatter(
            x=daily["date"],
            y=daily["cumulative_net_pnl"],
            mode="lines",
            line=dict(color=ACCENT_COLOR, width=2),
            fill="tozeroy",
            fillcolor="rgba(76,139,245,0.15)",
            hovertemplate="%{x|%Y-%m-%d}<br>Cumulative: %{y:$,.2f}<extra></extra>",
        )
    )
    fig.update_layout(title="Cumulative daily net P&L")
    return _style(fig)


def realized_r_hist(trades: pd.DataFrame) -> go.Figure | None:
    """Histogram of realized R across closed trades."""
    if trades is None or trades.empty or "realized_r" not in trades.columns:
        return None
    values = pd.to_numeric(trades["realized_r"], errors="coerce").dropna()
    if values.empty:
        return None
    fig = go.Figure(
        go.Histogram(
            x=values,
            nbinsx=max(8, min(30, int(values.nunique()))),
            marker_color=ACCENT_COLOR,
            hovertemplate="R in [%{x}]<br>count: %{y}<extra></extra>",
        )
    )
    fig.add_vline(x=0, line_width=1, line_dash="dash", line_color=GRID_COLOR)
    fig.update_layout(title="Realized R distribution", bargap=0.05)
    return _style(fig)


def cumulative_r_line(cumulative_r: pd.DataFrame) -> go.Figure | None:
    """Line/area chart of cumulative realized R over trading days."""
    if cumulative_r is None or cumulative_r.empty:
        return None
    fig = go.Figure(
        go.Scatter(
            x=cumulative_r["date"],
            y=cumulative_r["cumulative_realized_r"],
            mode="lines",
            line=dict(color=PROFIT_COLOR, width=2),
            fill="tozeroy",
            fillcolor="rgba(38,166,154,0.15)",
            hovertemplate="%{x|%Y-%m-%d}<br>Cumulative: %{y:.2f}R<extra></extra>",
        )
    )
    fig.update_layout(title="Cumulative realized R")
    return _style(fig)


def planned_rr_hist(values: pd.Series | None) -> go.Figure | None:
    """Histogram of planned reward-to-risk across trades."""
    if values is None:
        return None
    clean = pd.to_numeric(pd.Series(values), errors="coerce").dropna()
    if clean.empty:
        return None
    fig = go.Figure(
        go.Histogram(
            x=clean,
            nbinsx=max(6, min(24, int(clean.nunique()))),
            marker_color=ACCENT_COLOR,
            hovertemplate="RR in [%{x}]<br>count: %{y}<extra></extra>",
        )
    )
    fig.update_layout(title="Planned RR distribution", bargap=0.05)
    return _style(fig)


def weekday_bar(weekday: pd.DataFrame) -> go.Figure | None:
    """Bar chart of net P&L by weekday (green up / red down)."""
    if weekday is None or weekday.empty or "net_pnl" not in weekday.columns:
        return None
    colors = [PROFIT_COLOR if v >= 0 else LOSS_COLOR for v in weekday["net_pnl"]]
    fig = go.Figure(
        go.Bar(
            x=weekday["weekday"],
            y=weekday["net_pnl"],
            marker_color=colors,
            hovertemplate="%{x}<br>Net P&L: %{y:$,.2f}<extra></extra>",
        )
    )
    fig.update_layout(title="Performance by weekday")
    return _style(fig)


def calendar_heatmap(daily: pd.DataFrame) -> go.Figure | None:
    """GitHub-style calendar heatmap of daily net P&L (weekday x week)."""
    if daily is None or daily.empty:
        return None

    d = daily.copy()
    d["date"] = pd.to_datetime(d["date"])
    pnl_by_date = d.set_index("date")["net_pnl"]

    start = d["date"].min()
    monday0 = (start - pd.Timedelta(days=int(start.weekday()))).normalize()
    end = d["date"].max().normalize()
    n_weeks = int((end - monday0).days // 7) + 1

    weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    z = [[None] * n_weeks for _ in range(7)]
    text = [["" for _ in range(n_weeks)] for _ in range(7)]

    for date, value in pnl_by_date.items():
        week_idx = int((date.normalize() - monday0).days // 7)
        wd = int(date.weekday())
        if 0 <= week_idx < n_weeks:
            z[wd][week_idx] = float(value)
            text[wd][week_idx] = f"{date:%Y-%m-%d}<br>Net P&L: ${value:,.2f}"

    week_labels = [(monday0 + pd.Timedelta(weeks=w)).strftime("%b %d") for w in range(n_weeks)]

    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=week_labels,
            y=weekdays,
            text=text,
            hoverinfo="text",
            xgap=3,
            ygap=3,
            colorscale=[[0.0, LOSS_COLOR], [0.5, "rgba(150,150,150,0.25)"], [1.0, PROFIT_COLOR]],
            zmid=0,
            colorbar=dict(title="P&L"),
        )
    )
    fig.update_layout(title="Calendar heatmap of daily P&L")
    fig.update_yaxes(autorange="reversed")
    return _style(fig, height=280)


def equity_line(snapshots: pd.DataFrame) -> go.Figure | None:
    """Balance and equity over time from account snapshots."""
    if snapshots is None or snapshots.empty:
        return None
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=snapshots["timestamp"],
            y=snapshots["balance"],
            mode="lines+markers",
            name="Balance",
            line=dict(color=ACCENT_COLOR, width=2),
        )
    )
    if snapshots["equity"].notna().any():
        fig.add_trace(
            go.Scatter(
                x=snapshots["timestamp"],
                y=snapshots["equity"],
                mode="lines+markers",
                name="Equity",
                line=dict(color=PROFIT_COLOR, width=2, dash="dot"),
            )
        )
    fig.update_layout(title="Account balance / equity")
    return _style(fig)
