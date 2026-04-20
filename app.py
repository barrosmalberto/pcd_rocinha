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
    st.markdown("🏢 **Base Territorial (Gris):**<br>Polígonos com elevação sutil indicando a topografia do setor.", unsafe_allow_html=True)
    st.markdown("🎨 **Bolhas (Foco PCD):**<br>O tamanho e a cor indicam a concentração de PCDs.", unsafe_allow_html=True)
    st.markdown("🟡 **Amarelo:** Baixa Densidade")
    st.markdown("🔴 **Vermelho:** Alta Densidade")
    st.markdown("---")
    st.info("💡 **Dica:** Segure o botão direito do mouse para girar a maquete.")

st.title("🏔️ Acesso Vertical: PCDs na Rocinha")
st.caption("Análise técnica de correlação entre topografia e vulnerabilidade social.")

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
    
    # Cores do Terreno (Cinza Técnico)
    min_alt, max_alt = gdf['altitude'].min(), gdf['altitude'].max()
    gdf['cor_terreno'] = gdf['altitude'].apply(lambda x: [int(100 - (60 * (x-min_alt)/(max_alt-min_alt))), 
                                                         int(100 - (60 * (x-min_alt)/(max_alt-min_alt))), 
                                                         int(100 - (60 * (x-min_alt)/(max_alt-min_alt))), 180])

    # Cores e Posição das Bolhas
    min_pct = gdf['PCDS — Planilha1_%'].min()
    max_pct = gdf['PCDS — Planilha1_%'].max()
    gdf['posicao_bolha'] = gdf.apply(lambda r: [r.geometry.centroid.x, r.geometry.centroid.y, (r['altitude'] * 0.4) + 2], axis=1)
    
    def calc_cor(p):
        val = (p - min_pct) / (max_pct - min_pct) if max_pct > min_pct else 0
        return [255, int(255 * (1 - val)), 0, 230]
    
    gdf['cor_pcd'] = gdf['PCDS — Planilha1_%'].apply(calc_cor)
    gdf['raio_bolha'] = gdf['PCDS — Planilha1_%'].apply(lambda x: 15 + ((x - min_pct) / (max_pct - min_pct) * 40))
    
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
# 4. MAPA PYDECK (VERSÃO LAPIDADA)
# ==========================================
st.markdown("### Maquete Analítica da Rocinha")

# Camada de Terreno: Agora com elevação sutil e linhas de divisa
camada_terreno = pdk.Layer(
    "GeoJsonLayer",
    gdf_pcd,
    extruded=True,
    get_elevation="altitude",
    elevation_scale=0.4, # REDUZIDO: Para um visual mais elegante e menos 'Minecraft'
    get_fill_color="cor_terreno",
    get_line_color=[200, 200, 200, 150], # LINHA FINA: Cinza claro para dividir setores
    line_width_min_pixels=1, # Garante que a linha seja visível
    stroked=True,
    pickable=True,
)

# Camada de Bolhas: Mantendo o foco nos PCDs
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
    zoom=14.8, pitch=45, bearing=10
)

st.pydeck_chart(pdk.Deck(
    layers=[camada_terreno, camada_bolhas],
    initial_view_state=visao_mapa,
    map_style="dark",
    tooltip={"html": "<b>Setor:</b> {sub_bairro}<br><b>Altitude:</b> {altitude}m<br><b>PCDs:</b> {PCDS — Planilha1_%}"}
))

# ==========================================
# 5. PAINEL ANALÍTICO
# ==========================================
@st.fragment
def renderizar_graficos(df_final):
    st.divider()
    st.subheader("📊 Evidências e Metodologia")
    
    if df_final.empty:
        st.warning("Ajuste o filtro para visualizar os gráficos.")
        return

    df_plot = pd.DataFrame(df_final.drop(columns=['geometry']))
    df_plot['Faixa de Relevo'] = pd.qcut(df_plot['altitude'], q=3, 
                                        labels=['1. Baixo (Vales)', '2. Médio (Encostas)', '3. Alto (Topos)'])
    
    with st.expander("ℹ️ Nota Metodológica: O que são as Faixas de Relevo?"):
        st.write("""
            Utilizamos o critério estatístico de **Tercis** para classificar a topografia:
            - **Baixo:** O terço inferior das altitudes registradas (base da comunidade).
            - **Médio:** O terço intermediário (áreas de encosta).
            - **Alto:** O terço superior (cumes e áreas de maior dificuldade de acesso).
        """)

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
        color_discrete_map={'1. Baixo (Vales)': '#FFD700', '2. Médio (Encostas)': '#FF8C00', '3. Alto (Topos)': '#8B0000'},
        title="Dispersão: Altitude vs Densidade PCD"
    )
    st.plotly_chart(fig3, use_container_width=True)

    resumo = df_plot.groupby('Faixa de Relevo', observed=False)['PCDS — Planilha1_%'].mean().reset_index()
    fig4 = px.bar(resumo, x='Faixa de Relevo', y='PCDS — Planilha1_%',
                  title="Conclusão: Média de PCDs por Nível de Terreno",
                  color='Faixa de Relevo',
                  color_discrete_map={'1. Baixo (Vales)': '#FFD700', '2. Médio (Encostas)': '#FF8C00', '3. Alto (Topos)': '#8B0000'})
    st.plotly_chart(fig4, use_container_width=True)

renderizar_graficos(gdf_filtrado)
