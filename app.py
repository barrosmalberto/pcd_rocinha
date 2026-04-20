import streamlit as st
import pydeck as pdk
import pandas as pd
import geopandas as gpd
import numpy as np
import requests
import time
import plotly.graph_objects as go
import plotly.express as px

# ==========================================
# 1. CONFIGURAÇÃO E INTERFACE (SIDEBAR)
# ==========================================
st.set_page_config(page_title="Rocinha PCD & Hipsometria", layout="wide")

with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/814/814513.png", width=50)
    st.markdown("### 📌 Legenda Analítica")
    st.markdown("---")
    st.markdown("🏢 **Terreno (Z):**<br>Representa a altitude. Áreas mais escuras são os topos dos morros.", unsafe_allow_html=True)
    st.markdown("🎨 **Bolhas (PCDs):**<br>O tamanho e a cor indicam a concentração de PCDs.", unsafe_allow_html=True)
    st.markdown("🟡 **Amarelo:** Baixa Densidade")
    st.markdown("🔴 **Vermelho:** Alta Densidade")
    st.markdown("---")
    st.info("💡 **Dica:** Use o botão direito do rato para inclinar o mapa e ver a volumetria.")

st.title("🏔️ Acesso Vertical: PCDs na Rocinha")
st.caption("Análise de correlação entre topografia e vulnerabilidade social.")

# ==========================================
# 2. MOTOR DE DADOS (API E ETL)
# ==========================================

@st.cache_data(show_spinner=False)
def obter_elevacao_lote(df, lat_col="lat", lon_col="lon", chunk_size=100):
    elevacoes = []
    locations = [{"latitude": row[lat_col], "longitude": row[lon_col]} for _, row in df.iterrows()]
    url = "https://api.open-elevation.com/api/v1/lookup"
    
    progresso = st.progress(0, text="🌍 A consultar relevo (API Open-Elevation)...")
    
    for i in range(0, len(locations), chunk_size):
        chunk = locations[i : i + chunk_size]
        try:
            response = requests.post(url, json={"locations": chunk}, timeout=20)
            if response.status_code == 200:
                resultados = response.json().get("results", [])
                elevacoes.extend([res["elevation"] for res in resultados])
            else:
                elevacoes.extend([0] * len(chunk))
        except:
            elevacoes.extend([0] * len(chunk))
        
        time.sleep(1) # Respeito ao limite da API gratuita
        progresso.progress(min(1.0, (i + chunk_size) / len(locations)))
        
    progresso.empty()
    return elevacoes

@st.cache_data
def carregar_dados_completos():
    # Carregamento do arquivo enviado
    gdf = gpd.read_file("rocinha_pcds.geojson")
    if gdf.crs != "EPSG:4326":
        gdf = gdf.to_crs(epsg=4326)
        
    # Cálculo de Hipsometria
    with st.spinner("🌍 Mapeando altitudes dos setores..."):
        centroids = gdf.geometry.centroid
        temp_df = pd.DataFrame({'lat': centroids.y, 'lon': centroids.x})
        gdf['altitude'] = obter_elevacao_lote(temp_df)
    
    # Estética do Terreno (Cinza Subtil)
    min_alt, max_alt = gdf['altitude'].min(), gdf['altitude'].max()
    gdf['cor_terreno'] = gdf['altitude'].apply(lambda x: [int(120 - (80 * (x-min_alt)/(max_alt-min_alt))), 
                                                         int(120 - (80 * (x-min_alt)/(max_alt-min_alt))), 
                                                         int(120 - (80 * (x-min_alt)/(max_alt-min_alt))), 200])

    # Estética das Bolhas PCD
    min_pct = gdf['PCDS — Planilha1_%'].min()
    max_pct = gdf['PCDS — Planilha1_%'].max()
    
    # Posição 3D da bolha (flutuando levemente acima do solo)
    gdf['posicao_bolha'] = gdf.apply(lambda r: [r.geometry.centroid.x, r.geometry.centroid.y, r['altitude'] + 5], axis=1)
    
    # Cores e Raios
    def calc_cor(p):
        val = (p - min_pct) / (max_pct - min_pct) if max_pct > min_pct else 0
        return [255, int(255 * (1 - val)), 0, 230]
    
    gdf['cor_pcd'] = gdf['PCDS — Planilha1_%'].apply(calc_cor)
    gdf['raio_bolha'] = gdf['PCDS — Planilha1_%'].apply(lambda x: 15 + ((x - min_pct) / (max_pct - min_pct) * 40))
    
    return gdf

gdf_pcd = carregar_dados_completos()

# ==========================================
# 3. FILTROS E LÓGICA DE EXIBIÇÃO
# ==========================================
with st.sidebar:
    st.markdown("### 🎛️ Filtro de Densidade")
    valor_slider = st.slider(
        "Mostrar apenas setores com mais de (% PCD):",
        float(gdf_pcd['PCDS — Planilha1_%'].min()),
        float(gdf_pcd['PCDS — Planilha1_%'].max()),
        float(gdf_pcd['PCDS — Planilha1_%'].min()),
        format="%.4f"
    )

# Filtragem dos dados para as bolhas e gráficos
gdf_filtrado = gdf_pcd[gdf_pcd['PCDS — Planilha1_%'] >= valor_slider]

# ==========================================
# 4. MAPA PYDECK (VISUALIZAÇÃO 3D)
# ==========================================
st.markdown("### Maquete de Acessibilidade 3D")

camada_terreno = pdk.Layer(
    "GeoJsonLayer",
    gdf_pcd, # Terreno sempre completo para contexto
    extruded=True,
    get_elevation="altitude",
    elevation_scale=0.8,
    get_fill_color="cor_terreno",
    get_line_color=[255, 255, 255, 30],
    pickable=True,
)

camada_bolhas = pdk.Layer(
    "ScatterplotLayer",
    gdf_filtrado,
    get_position="posicao_bolha",
    get_radius="raio_bolha",
    radius_scale=1.2,
    get_fill_color="cor_pcd",
    get_line_color=[255, 255, 255, 255],
    stroked=True,
    line_width_min_pixels=1,
    pickable=True,
    auto_highlight=True
)

visao_mapa = pdk.ViewState(
    latitude=gdf_pcd.geometry.centroid.y.mean(),
    longitude=gdf_pcd.geometry.centroid.x.mean(),
    zoom=14.5, pitch=50, bearing=10
)

st.pydeck_chart(pdk.Deck(
    layers=[camada_terreno, camada_bolhas],
    initial_view_state=visao_mapa,
    map_style="dark",
    tooltip={"html": "<b>Setor:</b> {sub_bairro}<br><b>Altitude:</b> {altitude}m<br><b>PCDs:</b> {PCDS — Planilha1_%}"}
))

# ==========================================
# 5. PAINEL ANALÍTICO (GRÁFICOS SIMPLIFICADOS)
# ==========================================
@st.fragment
def renderizar_graficos(df_final):
    st.divider()
    st.subheader("📊 Evidências Analíticas")
    
    if df_final.empty:
        st.warning("Ajuste o filtro para visualizar os gráficos.")
        return

    # Limpeza para o Plotly
    df_plot = pd.DataFrame(df_final.drop(columns=['geometry']))

    # --- GRÁFICO 1: Altitude (Decrescente) ---
    df_alt = df_plot.sort_values('altitude', ascending=False)
    fig1 = px.line(df_alt, x='sub_bairro', y='altitude', markers=True, title="1. Perfil de Altitude por Setor")
    fig1.update_traces(line_color='grey', marker=dict(color='crimson', size=8))
    fig1.update_layout(xaxis_title=None, yaxis_title="Metros")
    st.plotly_chart(fig1, use_container_width=True)

    # --- GRÁFICO 2: Percentual PCD (Decrescente) ---
    df_pcd_ord = df_plot.sort_values('PCDS — Planilha1_%', ascending=False)
    fig2 = px.bar(df_pcd_ord, x='sub_bairro', y='PCDS — Planilha1_%', title="2. Concentração de PCDs por Setor")
    fig2.update_traces(marker_color='darkorange')
    fig2.update_layout(xaxis_title=None, yaxis_title="Percentual (%)")
    st.plotly_chart(fig2, use_container_width=True)

    # --- GRÁFICO 3: SÍNTESE DA HIPÓTESE (O mais importante) ---
    # Classificação simplificada em 3 níveis
    df_plot['Faixa de Relevo'] = pd.qcut(df_plot['altitude'], q=3, 
                                        labels=['Baixo (Vales)', 'Médio (Encostas)', 'Alto (Topos)'])
    
    resumo_hipotese = df_plot.groupby('Faixa de Relevo', observed=False)['PCDS — Planilha1_%'].mean().reset_index()
    
    fig3 = px.bar(resumo_hipotese, x='Faixa de Relevo', y='PCDS — Planilha1_%',
                  title="3. CONCLUSÃO: Onde vivem os PCDs? (Média por Faixa de Relevo)",
                  color='Faixa de Relevo',
                  color_discrete_map={'Baixo (Vales)': '#FFD700', 'Médio (Encostas)': '#FF8C00', 'Alto (Topos)': '#8B0000'})
    
    fig3.update_layout(showlegend=False, yaxis_title="Média de PCDs (%)", xaxis_title=None)
    st.plotly_chart(fig3, use_container_width=True)

renderizar_graficos(gdf_filtrado)
