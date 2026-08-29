"""Phase 11 Streamlit interface for the latest auditable scan."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.data import (
    filter_scan,
    index_choices,
    latest_scan_report,
    load_latest_fundamental,
    load_price_history,
    load_scan_report,
    scenario_rows,
)

HORIZONS = [3, 6, 12, 18, 24]


def _number(value: Any, suffix: str = "", digits: int = 2) -> str:
    try:
        if pd.isna(value):
            return "Indisponible"
        return f"{float(value):,.{digits}f}{suffix}".replace(",", " ")
    except (TypeError, ValueError):
        return "Indisponible"


def _percent(value: Any) -> str:
    try:
        if pd.isna(value):
            return "Indisponible"
        return f"{float(value):+.1%}"
    except (TypeError, ValueError):
        return "Indisponible"


def _coverage(value: Any) -> str:
    try:
        if pd.isna(value):
            return "Indisponible"
        return f"{float(value):.1%}"
    except (TypeError, ValueError):
        return "Indisponible"


def _analytical_verdict(row: pd.Series) -> str:
    coverage, score = row.get("opportunity_score_coverage"), row.get("opportunity_score")
    if pd.isna(coverage) or float(coverage) < 0.50 or pd.isna(score):
        return "Non classé — couverture insuffisante"
    if float(score) >= 70:
        return "Priorité analytique élevée"
    if float(score) >= 50:
        return "À approfondir"
    return "Priorité analytique faible"


def _sidebar(frame: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    st.sidebar.header("Filtres")
    country_column = "listing_country" if "listing_country" in frame else "country"
    countries = st.sidebar.multiselect("Pays de cotation", sorted(frame[country_column].dropna().unique()))
    sectors = st.sidebar.multiselect("Secteur", sorted(frame["sector"].dropna().unique()))
    indices = st.sidebar.multiselect("Indice", index_choices(frame))
    minimum_score = st.sidebar.slider("Score d'opportunité minimum", 0, 100, 0)
    maximum_drawdown_pct = st.sidebar.slider(
        "Drawdown 52 semaines maximal", -100, 0, 0,
        help="-20 % conserve les titres à -20 % ou moins par rapport au plus haut 52 semaines.",
    )
    minimum_market_cap_bn = st.sidebar.number_input(
        "Capitalisation minimale (Md EUR)", min_value=0.0, value=0.0, step=1.0
    )
    shock_labels = {
        "Temporaire": "temporary", "Structurel": "structural",
        "Mixte": "mixed", "Indisponible": "data_unavailable",
    }
    selected_shocks = st.sidebar.multiselect("Nature du choc", list(shock_labels))
    minimum_risk = st.sidebar.slider(
        "Résilience minimale", 0, 100, 0,
        help="Le Risk Score mesure la résilience : plus haut signifie un risque mesuré plus faible.",
    )
    horizon = st.sidebar.select_slider(
        "Horizon", options=HORIZONS, value=12, format_func=lambda value: f"{value} mois"
    )
    return filter_scan(
        frame, countries=countries, sectors=sectors, indices=indices,
        minimum_score=float(minimum_score), maximum_drawdown=maximum_drawdown_pct / 100,
        minimum_market_cap_eur=minimum_market_cap_bn * 1_000_000_000,
        shock_natures=[shock_labels[value] for value in selected_shocks],
        minimum_risk_score=float(minimum_risk),
    ), horizon


def _top_table(frame: pd.DataFrame) -> None:
    columns = [
        "ticker", "company", "listing_country", "sector", "index_memberships",
        "opportunity_score", "opportunity_score_coverage", "drawdown_52w",
        "fair_value", "base_target", "risk_reward", "data_quality",
    ]
    available = [column for column in columns if column in frame]
    table = frame.sort_values(
        ["opportunity_score", "decline_severity_score"], ascending=[False, False], na_position="last"
    )[available].head(50).rename(columns={
        "ticker": "Ticker", "company": "Société", "listing_country": "Pays",
        "sector": "Secteur", "index_memberships": "Indice", "opportunity_score": "Score",
        "opportunity_score_coverage": "Couverture", "drawdown_52w": "Drawdown 52s",
        "fair_value": "Juste valeur", "base_target": "Objectif Base",
        "risk_reward": "Risque/rendement", "data_quality": "Qualité",
    })
    st.dataframe(table, width="stretch", hide_index=True, column_config={
        "Score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f"),
        "Couverture": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.0f%%"),
        "Drawdown 52s": st.column_config.NumberColumn(format="percent"),
        "Juste valeur": st.column_config.NumberColumn(format="%.2f"),
        "Objectif Base": st.column_config.NumberColumn(format="%.2f"),
    })


def _price_panel(ticker: str) -> None:
    prices = load_price_history(ticker)
    if prices.empty:
        st.info("Historique de prix normalisé indisponible pour ce titre.")
        return
    chart = go.Figure()
    chart.add_trace(go.Scatter(x=prices["observation_date"], y=prices["adjusted_close"], name="Cours ajusté", line={"color": "#4ED3A8", "width": 2}))
    chart.add_trace(go.Scatter(x=prices["observation_date"], y=prices["ma50"], name="MM50", line={"color": "#F4B942", "width": 1.3}))
    chart.add_trace(go.Scatter(x=prices["observation_date"], y=prices["ma200"], name="MM200", line={"color": "#EB6F92", "width": 1.3}))
    chart.update_layout(height=430, margin=dict(l=10, r=10, t=25, b=10), hovermode="x unified", legend=dict(orientation="h"))
    st.plotly_chart(chart, width="stretch")


def _fundamental_panel(ticker: str) -> None:
    payload = load_latest_fundamental(ticker)
    if not payload or not payload.get("annual_observations"):
        st.info("Fondamentaux annuels point-in-time indisponibles. Les sociétés européennes sans dépôt SEC nécessitent encore une source ESEF/IFRS.")
        return
    observations = payload["annual_observations"]
    chart = go.Figure()
    for metric, label in (("revenue", "Chiffre d'affaires"), ("operating_cash_flow", "Cash-flow opérationnel"), ("capex", "Capex")):
        items = observations.get(metric, [])
        if items:
            chart.add_trace(go.Bar(x=[item["end_date"] for item in items], y=[item["value"] for item in items], name=label))
    chart.update_layout(barmode="group", height=390, margin=dict(l=10, r=10, t=25, b=10), legend=dict(orientation="h"))
    st.plotly_chart(chart, width="stretch")
    metrics = payload.get("metrics", {})
    names = ("revenue_cagr", "eps_cagr", "fcf_cagr", "gross_margin", "operating_margin", "net_margin", "fcf_margin", "roe", "debt_to_equity", "net_debt_to_ebitda")
    st.dataframe(pd.DataFrame([
        {"Métrique": name, "Valeur": (metrics.get(name) or {}).get("value"), "Statut": (metrics.get(name) or {}).get("status")}
        for name in names
    ]), hide_index=True, width="stretch")
    st.caption(f"Disponibilité conservée au {payload.get('as_of', 'inconnue')} · dernière période {payload.get('latest_period_end', 'indisponible')}")


def _scenario_panel(row: pd.Series, horizon: int) -> None:
    payload = row.get("scenario_metrics") if isinstance(row.get("scenario_metrics"), dict) else {}
    rows = scenario_rows(payload, horizon)
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    else:
        st.info("Scénarios non calculables avec les données actuellement couvertes.")
    st.caption("Les objectifs sont des sorties de modèles sourcés et non des prévisions garanties.")


def _evidence_panel(row: pd.Series) -> None:
    st.write(row.get("shock_conclusion") or "Aucune conclusion causale suffisamment documentée.")
    cols = st.columns(4)
    cols[0].metric("Catégorie", str(row.get("shock_category") or "Indisponible"))
    cols[1].metric("Nature", str(row.get("shock_nature") or "Indisponible"))
    cols[2].metric("Sources indépendantes", _number(row.get("shock_independent_source_count"), digits=0))
    cols[3].metric("Score choc", _number(row.get("temporary_shock_score")))
    sources = row.get("sources") if isinstance(row.get("sources"), list) else []
    links = [{"Source": source.get("name") or source.get("source"), "Rôle": source.get("role"), "URL": source.get("url") or source.get("source_url")} for source in sources]
    if links:
        st.dataframe(pd.DataFrame(links).drop_duplicates(), hide_index=True, width="stretch", column_config={"URL": st.column_config.LinkColumn()})


def _detail(frame: pd.DataFrame, horizon: int) -> None:
    reset = frame.reset_index(drop=True)
    labels = {f"{row.ticker} · {row.company if pd.notna(row.company) else 'Société non renseignée'}": index for index, row in reset.iterrows()}
    selected_label = st.selectbox("Société analysée", list(labels))
    row = reset.iloc[labels[selected_label]]
    st.subheader(f"{row.get('company') or row['ticker']}  ·  {row['ticker']}")
    st.caption(f"{row.get('listing_country') or row.get('country')} · {row.get('sector')} · {row.get('index_memberships', 'Hors indice renseigné')}")
    metrics = st.columns(6)
    metrics[0].metric("Cours", f"{_number(row.get('current_price'))} {row.get('currency') or ''}")
    metrics[1].metric("Score", _number(row.get("opportunity_score")))
    metrics[2].metric("Couverture", _coverage(row.get("opportunity_score_coverage")))
    metrics[3].metric("Drawdown 52s", _percent(row.get("drawdown_52w")))
    metrics[4].metric("Objectif Base", _number(row.get("base_target")))
    metrics[5].metric("Risque/rendement", _number(row.get("risk_reward")))
    st.info(_analytical_verdict(row) + " — ce classement n'est pas une recommandation d'investissement.")
    overview, price, fundamentals, valuation, evidence, scenarios, analyst = st.tabs([
        "Synthèse", "Prix", "Fondamentaux", "Valorisation", "Choc & preuves", "Scénarios", "Analyste IA",
    ])
    with overview:
        score_rows = [
            {"Dimension": label, "Score": row.get(column), "Couverture": row.get(coverage)}
            for label, column, coverage in (
                ("Qualité fondamentale", "fundamental_quality_score", "fundamental_quality_coverage"),
                ("Valorisation", "valuation_score", "valuation_coverage"),
                ("Choc temporaire", "temporary_shock_score", "temporary_shock_coverage"),
                ("Résilience", "risk_score", "risk_score_coverage"),
                ("Opportunité", "opportunity_score", "opportunity_score_coverage"),
            )
        ]
        st.dataframe(pd.DataFrame(score_rows), hide_index=True, width="stretch")
        if row.get("fundamental_invalidation"):
            st.write("Conditions d'invalidation")
            st.json(row.get("fundamental_invalidation"), expanded=False)
    with price:
        _price_panel(str(row["ticker"]))
    with fundamentals:
        _fundamental_panel(str(row["ticker"]))
    with valuation:
        st.dataframe(pd.DataFrame([
            {"Méthode": label, "Actuel": row.get(current), "Historique": row.get(historical), "Secteur": row.get(sector)}
            for label, current, historical, sector in (
                ("P/E", "pe_current", "pe_historical_median", "pe_sector_median"),
                ("EV/EBITDA", "ev_ebitda_current", "ev_ebitda_historical_median", "ev_ebitda_sector_median"),
                ("Prix/FCF", "price_fcf_current", "price_fcf_historical_median", "price_fcf_sector_median"),
            )
        ]), hide_index=True, width="stretch")
        st.write({"DCF Bear": row.get("dcf_bear_value_per_share"), "DCF Base": row.get("dcf_base_value_per_share"), "DCF Bull": row.get("dcf_bull_value_per_share"), "Valeur normalisée": row.get("normalized_value_per_share")})
    with evidence:
        _evidence_panel(row)
    with scenarios:
        _scenario_panel(row, horizon)
    with analyst:
        st.warning("L'analyste IA critique est volontairement désactivé : aucune clé API distincte ni historique de validation n'est configuré. Les cas Bull/Bear, catalyseurs et risques ne sont donc pas inventés.")


def main() -> None:
    st.set_page_config(page_title="AI Stock Opportunity Scanner", page_icon="◈", layout="wide")
    st.markdown("""
    <style>
      .stApp {background: radial-gradient(circle at 85% 0%, #122a35 0, #07151c 35%, #050b10 100%);}
      [data-testid="stMetric"] {background: rgba(21,45,55,.72); border: 1px solid rgba(78,211,168,.18); padding: 14px; border-radius: 12px;}
      h1, h2, h3 {letter-spacing: -.025em;}
    </style>
    """, unsafe_allow_html=True)
    st.title("AI Stock Opportunity Scanner")
    st.caption("Moteur point-in-time · prix, fondamentaux, valorisation, chocs, scénarios et couverture des preuves")
    report = latest_scan_report()
    if report is None:
        st.error("Aucun scan disponible. Lancez d'abord `python -m src.pipeline` depuis la racine du projet.")
        return
    frame = load_scan_report(report)
    modified = datetime.fromtimestamp(report.stat().st_mtime).astimezone()
    st.caption(f"Dernière mise à jour : {modified:%d/%m/%Y %H:%M %Z} · fichier {report.name} · {len(frame)} titres")
    filtered, horizon = _sidebar(frame)
    head = st.columns(4)
    head[0].metric("Titres visibles", len(filtered))
    head[1].metric("Candidats", int(filtered.get("is_candidate", pd.Series(dtype=bool)).fillna(False).sum()))
    head[2].metric("Pays", filtered.get("listing_country", filtered.get("country", pd.Series(dtype=str))).nunique())
    coverage = pd.to_numeric(filtered.get("opportunity_score_coverage", pd.Series(dtype=float)), errors="coerce").mean()
    head[3].metric("Couverture moyenne", _coverage(coverage))
    if filtered.empty:
        st.warning("Aucun titre ne satisfait l'ensemble des filtres.")
        return
    st.subheader("Meilleures opportunités mesurées")
    _top_table(filtered)
    st.divider()
    st.subheader("Fiche société")
    _detail(filtered, horizon)
    st.caption("Les scores sont des indicateurs analytiques ajustés de leur couverture, jamais des probabilités de gain. Données manquantes affichées comme telles.")


if __name__ == "__main__":
    main()
