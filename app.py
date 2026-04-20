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
# Se você já mudou no .streamlit/config.toml, o Streamlit vai respeitar o Light Theme global.
st.set_page_config(page_title="Rocinha PCD & Hipsometria", layout="wide")

with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/814/814513.png", width=50)
    st.markdown("### 📌 Legenda Analítica")
    st.markdown("---")
    st.markdown("🏢 **Malha Territorial (Altimetria):**<br>Relevo suavizado. *Verde-Água* (áreas baixas), *Ametista* (encostas) e *Terracota* (topos).", unsafe_allow_html=True)
    st.markdown("🎨 **Indicadores PCD (Bolhas):**<br>O tamanho e a cor indicam a concentração de PCDs.", unsafe_allow_html=True)
    st.markdown("🟡 **Amarelo:** Baixa Densidade")
    st.markdown("🔴 **Vermelho:** Alta Densidade")
    st.markdown("---")
    st.info("💡 **Dica:** Use o botão direito do mouse para girar a maquete interativa.")

st.title("🏔️ Acesso Vertical: PCDs na Rocinha")
st.caption("Visualização técnica refinada: Correlação entre topografia e vulnerabilidade.")

# ==========================================
# 2. MOTOR DE DADOS (API E ETL)
# ==========================================

@st.cache_data(show_spinner=False)
def obter_elevacao_lote(df, lat_col="lat", lon_col="lon", chunk_size=100):
    elevacoes = []
    locations = [{"latitude": row[lat_col], "longitude": row[lon_col]} for _, row in df.iterrows()]
    url = "https://api.open-elevation.com/api/v1/lookup"
    
    progresso = st.progress(0, text="🌍 Consultando relevo (API Open-Elevation)...")
    
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
        
        time.sleep(1) 
        progresso.progress(min(1.0, (i + chunk_size) / len(locations)))
        
    progresso.empty()
    return elevacoes

@st.cache_data
def carregar_dados_completos():
    gdf = gpd.read_file("rocinha_pcds.geojson")
    if gdf.crs != "EPSG:4326":
        gdf = gdf.to_crs(epsg=4326)
        
    with st.spinner("🌍 Mapeando altitudes dos setores..."):
        centroids = gdf.geometry.centroid
        temp_df = pd.DataFrame({'lat': centroids.y, 'lon': centroids.x})
        gdf['altitude'] = obter_elevacao_lote(temp_df)
    
    min_alt, max_alt = gdf['altitude'].min(), gdf['altitude'].max()
    
    # --- NOVA ESTÉTICA DO TERRENO: Cores Vibrantes para Light Theme ---
    def cor_altimetria_light(alt):
        frac = (alt - min_alt) / (max_alt - min_alt) if max_alt > min_alt else 0
        if frac < 0.5:
            # Transição: Verde-Água (130, 200, 200) para Ametista (150, 120, 190)
            f_norm = frac * 2
            r = int(130 + (150 - 130) * f_norm)
            g = int(200 + (120 - 200) * f_norm)
            b = int(200 + (190 - 200) * f_norm)
        else:
            # Transição: Ametista (150, 120, 190) para Terracota (220, 100, 110)
            f_norm = (frac - 0.5) * 2
            r = int(150 + (220 - 150) * f_norm)
            g = int(120 + (100 - 120) * f_norm)
            b = int(190 + (110 - 190) * f_norm)
        return [r, g, b, 180] # Alpha 180 para não desbotar contra o branco
        
    gdf['cor_terreno'] = gdf['altitude'].apply(cor_altimetria_light)

    # Cores e Posição das Bolhas
    min_pct = gdf['PCDS — Planilha1_%'].min()
    max_pct = gdf['PCDS — Planilha1_%'].max()
    gdf['posicao_bolha'] = gdf.apply(lambda r: [r.geometry.centroid.x, r.geometry.centroid.y, (r['altitude'] * 0.2) + 1.5], axis=1)
    
    def calc_cor_light(p):
        val = (p - min_pct) / (max_pct - min_pct) if max_pct > min_pct else 0
        # Amarelo Ouro [255, 200, 0] para Vermelho Escuro [180, 0, 0]
        return [int(255 - (75 * val)), int(200 * (1 - val)), 0, 230]
    
    gdf['cor_pcd'] = gdf['PCDS — Planilha1_%'].apply(calc_cor_light)
    gdf['raio_bolha'] = gdf['PCDS — Planilha1_%'].apply(lambda x: 12 + ((x - min_pct) / (max_pct - min_pct) * 38))
    
    return gdf

gdf_pcd = carregar_dados_completos()

# ==========================================
# 3. FILTROS
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

gdf_filtrado = gdf_pcd[gdf_pcd['PCDS — Planilha1_%'] >= valor_slider]

# ==========================================
# 4. MAPA PYDECK (VERSÃO LIGHT THEME)
# ==========================================
st.markdown("### Maquete Técnica Interativa")

camada_terreno = pdk.Layer(
    "GeoJsonLayer",
    gdf_pcd,
    extruded=True,
    get_elevation="altitude",
    elevation_scale=0.2, 
    get_fill_color="cor_terreno", 
    get_line_color=[80, 80, 80, 200], # GRAFITE ESCURO: Define as fronteiras contra o fundo claro
    line_width_min_pixels=1.5, 
    stroked=True,
    pickable=True,
)

camada_bolhas = pdk.Layer(
    "ScatterplotLayer",
    gdf_filtrado,
    get_position="posicao_bolha",
    get_radius="raio_bolha",
    radius_scale=1.1,
    get_fill_color="cor_pcd",
    get_line_color=[40, 40, 40, 255], # GRAFITE SÓLIDO: Para destacar a bolha do terreno colorido
    stroked=True,
    line_width_min_pixels=1.5,
    pickable=True,
    auto_highlight=True
)

visao_mapa = pdk.ViewState(
    latitude=gdf_pcd.geometry.centroid.y.mean(),
    longitude=gdf_pcd.geometry.centroid.x.mean(),
    zoom=15.2, 
    pitch=45,  # AQUI ESTÁ A MAGIA: Angulação exata de 45° 📐
    bearing=5  # Mantemos uma ligeira rotação (5°) para que a malha não fique totalmente reta
)
st.pydeck_chart(pdk.Deck(
    layers=[camada_terreno, camada_bolhas],
    initial_view_state=visao_mapa,
    map_style="light", # ATUALIZADO: Fundo do mapa configurado para o estilo claro (Road/Light)
    tooltip={"html": "<b>Setor:</b> {sub_bairro}<br><b>Altitude:</b> {altitude}m<br><b>PCDs:</b> {PCDS — Planilha1_%}"}
))

# ==========================================
# 5. PAINEL ANALÍTICO
# ==========================================
@st.fragment
def renderizar_graficos(df_final):
    st.divider()
    st.subheader("📊 Evidências Analíticas")
    
    if df_final.empty:
        st.warning("Ajuste o filtro para visualizar os gráficos.")
        return

    df_plot = pd.DataFrame(df_final.drop(columns=['geometry']))
    df_plot['Faixa de Relevo'] = pd.qcut(df_plot['altitude'], q=3, 
                                        labels=['1. Baixo (Vales)', '2. Médio (Encostas)', '3. Alto (Topos)'])
    
    with st.expander("ℹ️ Nota Metodológica"):
        st.write("Classificação topográfica baseada em tercis estatísticos das altitudes da região.")

    col1, col2 = st.columns(2)
    with col1:
        df_alt = df_plot.sort_values('altitude', ascending=False)
        fig1 = px.line(df_alt, x='sub_bairro', y='altitude', markers=True, title="Perfil de Altitude por Setor")
        fig1.update_traces(line_color='grey', marker=dict(color='crimson'))
        st.plotly_chart(fig1, use_container_width=True)

    with col2:
        df_pcd_ord = df_plot.sort_values('PCDS — Planilha1_%', ascending=False)
        fig2 = px.bar(df_pcd_ord, x='sub_bairro', y='PCDS — Planilha1_%', title="Concentração de PCDs por Setor")
        fig2.update_traces(marker_color='darkorange')
        st.plotly_chart(fig2, use_container_width=True)

    st.markdown("#### Matriz de Correlação Clusterizada")
    fig3 = px.scatter(
        df_plot, x='altitude', y='PCDS — Planilha1_%',
        color='Faixa de Relevo', size='PCDS — Planilha1_%',
        hover_name='sub_bairro',
        # Cores adaptadas para melhor contraste em fundo claro
        color_discrete_map={'1. Baixo (Vales)': '#FFB300', '2. Médio (Encostas)': '#FF7F00', '3. Alto (Topos)': '#D32F2F'},
        title="Dispersão: Altitude vs Densidade PCD"
    )
    # Borda escura nas bolhas do gráfico
    fig3.update_traces(marker=dict(line=dict(width=1, color='DarkSlateGrey')))
    st.plotly_chart(fig3, use_container_width=True)

    resumo = df_plot.groupby('Faixa de Relevo', observed=False)['PCDS — Planilha1_%'].mean().reset_index()
    fig4 = px.bar(resumo, x='Faixa de Relevo', y='PCDS — Planilha1_%',
                  title="Conclusão: Média de PCDs por Nível de Terreno",
                  color='Faixa de Relevo',
                  color_discrete_map={'1. Baixo (Vales)': '#FFB300', '2. Médio (Encostas)': '#FF7F00', '3. Alto (Topos)': '#D32F2F'})
    st.plotly_chart(fig4, use_container_width=True)

renderizar_graficos(gdf_filtrado)
