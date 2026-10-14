"""Painel de desempenho das criptomoedas, a partir dos candles diários em data/raw/ohlcv.

Uso:
    uv run streamlit run app.py
"""

from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from market_metrics import monthly_returns, normalized, summarize, to_wide
from signal_analyzer import load_closes

DATA_DIR = Path("data/raw/ohlcv")
EXCHANGE = "binance"
TOP_DEFAULT = 5

# rótulo -> (coluna, ordenação decrescente?)
RANKINGS = {
    "Mais subindo no mês": ("ret_mes", True),
    "Mais caindo no mês": ("ret_mes", False),
    "Mais subindo em 1 ano": ("ret_1a", True),
    "Mais caindo em 1 ano": ("ret_1a", False),
    "Sem cair há mais tempo": ("dias_sem_queda", True),
    "Maior queda (drawdown 1 ano)": ("max_dd_1a", False),
}
WINDOWS = {"Mês atual": 0, "3 meses": 90, "1 ano": 365, "Tudo": None}


@st.cache_data(ttl=3600)
def load_wide() -> pd.DataFrame:
    return to_wide(load_closes(DATA_DIR, EXCHANGE, "1d"))


st.set_page_config(page_title="Cripto — desempenho", layout="wide")
st.title("Desempenho das criptomoedas")

if not DATA_DIR.exists():
    st.warning(f"Pasta {DATA_DIR} não encontrada. Rode extract_historical.py primeiro.")
    st.stop()

wide = load_wide()
if wide.empty:
    st.info("Nenhum dado de candle encontrado. Rode a extração primeiro.")
    st.stop()

ref = wide.index.max()
table = summarize(wide, ref)
if table.empty:
    st.info("Nenhum ativo com candle recente.")
    st.stop()

st.caption(f"Dados até {ref:%d/%m/%Y} · {len(table)} ativo(s) ativos")

# ---- controles ----
with st.sidebar:
    st.header("Filtros")
    ranking = st.selectbox("Ordenar ranking por", list(RANKINGS))
    window = st.radio("Período do gráfico", list(WINDOWS), index=2)
    col, desc = RANKINGS[ranking]
    ordered = table.sort_values(col, ascending=not desc).index.tolist()
    selected = st.multiselect(
        "Moedas nos gráficos",
        options=sorted(table.index),
        default=ordered[:TOP_DEFAULT],
    )

# ---- ranking ----
st.subheader(ranking)
view = table.sort_values(col, ascending=not desc).copy()
for pct in ["ret_mes", "ret_3m", "ret_1a", "max_dd_1a"]:
    view[pct] = view[pct] * 100
st.dataframe(
    view,
    column_config={
        "preco": st.column_config.NumberColumn("Preço", format="%.4f"),
        "ret_mes": st.column_config.NumberColumn("Retorno mês", format="%.1f%%"),
        "ret_3m": st.column_config.NumberColumn("Retorno 3m", format="%.1f%%"),
        "ret_1a": st.column_config.NumberColumn("Retorno 1 ano", format="%.1f%%"),
        "max_dd_1a": st.column_config.NumberColumn("Drawdown 1 ano", format="%.1f%%"),
        "dias_sem_queda": st.column_config.NumberColumn("Dias sem cair", format="%d"),
        "dias_historico": st.column_config.NumberColumn("Dias de histórico", format="%d"),
    },
    width="stretch",
)

if not selected:
    st.info("Selecione ao menos uma moeda na barra lateral.")
    st.stop()

# ---- evolução de preço ----
days = WINDOWS[window]
if days is None:
    start = None
elif days == 0:
    start = ref.replace(day=1)
else:
    start = ref - pd.Timedelta(days=days)

st.subheader("Evolução (base 100 no início do período)")
norm = normalized(wide, selected, start)
fig = px.line(norm, labels={"value": "Índice", "timestamp": "Data", "variable": "Moeda"})
fig.update_layout(legend_title_text="", margin=dict(t=10))
st.plotly_chart(fig)

# ---- mapa de calor mensal ----
st.subheader("Retorno mensal (últimos 24 meses)")
mr = monthly_returns(wide[selected], months=24) * 100
mr.index = mr.index.strftime("%m/%Y")
heat = px.imshow(
    mr.T,
    color_continuous_scale="RdYlGn",
    color_continuous_midpoint=0,
    aspect="auto",
    labels={"x": "Mês", "y": "Moeda", "color": "%"},
    text_auto=".0f",
)
heat.update_layout(margin=dict(t=10))
st.plotly_chart(heat)
