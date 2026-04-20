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
    
    # --- NOVO: SELETOR DE LENTE ANALÍTICA ---
    st.markdown("### 🔍 Modo de Visualização")
    modo_analise = st.radio(
        "Selecione a camada do terreno:",
        ["Hipsometria (Altitude)", "Declividade (Inclinação)"]
    )
    
    st.markdown("### 🗺️ Estilo do Mapa")
    estilos_mapa = {"Claro (Padrão)": "light", "Modo Escuro": "dark"}
    mapa_selecionado = st.selectbox("Escolha a base de visualização:", list(estilos_mapa.keys()))
    basemap_pdk = estilos_mapa[mapa_selecionado]
    
    st.markdown("---")
    if modo_analise == "Hipsometria (Altitude)":
        st.markdown("🏢 **Malha Territorial:**<br>Verde-Água (áreas baixas) a Terracota (topos).", unsafe_allow_html=True)
    else:
        st.markdown("🏢 **Malha Territorial:**<br>Verde (Plano) a Roxo (Aclive Crítico).", unsafe_allow_html=True)

    st.markdown("🎨 **Indicadores PCD (Bolhas):**")
    st.markdown("🟡 **Amarelo:** Baixa Densidade")
    st.markdown("🟠 **Laranja:** Média Densidade")
    st.markdown("🔴 **Vermelho:** Alta Densidade")
    st.markdown("---")
    st.info("💡 **Dica:** Use o botão direito do rato para inclinar a maquete.")

st.title("🏔️ Índice de Acessibilidade Vertical: Rocinha")
st.caption("Análise multivariada de topografia, inclinação e vulnerabilidade espacial.")

# ==========================================
# 2. MOTOR DE DADOS (API E ETL EXPANDIDO)
# ==========================================

@st.cache_data(show_spinner=False)
def obter_elevacao_lote(df, lat_col="lat", lon_col="lon", chunk_size=100):
    elevacoes = []
    locations = [{"latitude": row[lat_col], "longitude": row[lon_col]} for _, row in df.iterrows()]
    url = "https://api.open-elevation.com/api/v1/lookup"
    for i in range(0, len(locations), chunk_size):
        chunk = locations[i : i + chunk_size]
        try:
            response = requests.post(url, json={"locations": chunk}, timeout=20)
            if response.status_code == 200:
                resultados = response.json().get("results", [])
                elevacoes.extend([res["elevation"] for res in resultados])
            else: elevacoes.extend([0] * len(chunk))
        except: elevacoes.extend([0] * len(chunk))
        time.sleep(0.5) 
    return elevacoes

@st.cache_data
def carregar_dados_completos():
    gdf = gpd.read_file("rocinha_pcds.geojson")
    if gdf.crs != "EPSG:4326": gdf = gdf.to_crs(epsg=4326)
    
    # Normalização de Nomes e Valores
    gdf = gdf.rename(columns={'PCDS — Planilha1_%': 'Percentual de PCDs'})
    gdf['Percentual de PCDs'] = gdf['Percentual de PCDs'] * 100 
        
    with st.spinner("🌍 Calculando Hipsometria e Declividade (NBR 9050)..."):
        centroids = gdf.geometry.centroid
        # PONTO A (Centroide) e PONTO B (Offset lateral de ~55m)
        df_pontos = pd.DataFrame({
            'lat': centroids.y, 'lon': centroids.x,
            'lat_b': centroids.y + 0.0005, 'lon_b': centroids.x
        })
        
        alt_a = obter_elevacao_lote(df_pontos[['lat', 'lon']])
        alt_b = obter_elevacao_lote(df_pontos.rename(columns={'lat_b':'lat', 'lon_b':'lon'})[['lat', 'lon']])
        
        gdf['altitude'] = alt_a
        # Fórmula de Declividade: (Diferença Altura / Distância) * 100
        gdf['declividade'] = abs(np.array(alt_a) - np.array(alt_b)) / 55 * 100

    # Cores Hipsométricas (Lógica Ouro Preservada)
    min_alt, max_alt = gdf['altitude'].min(), gdf['altitude'].max()
    def cor_alt(alt):
        frac = (alt - min_alt) / (max_alt - min_alt) if max_alt > min_alt else 0
        if frac < 0.5:
            f = frac * 2
            return [int(130+(150-130)*f), int(200+(120-200)*f), int(200+(190-200)*f), 180]
        f = (frac - 0.5) * 2
        return [int(150+(220-150)*f), int(120+(100-120)*f), int(190+(110-190)*f), 180]
    gdf['cor_altitude'] = gdf['altitude'].apply(cor_alt)

    # Cores de Declividade (Lógica Nova: Verde -> Laranja -> Roxo)
    def cor_slope(slope):
        if slope < 5: return [46, 204, 113, 180]    # Plano (Verde)
        elif slope < 12: return [230, 126, 34, 180] # Íngreme (Laranja)
        else: return [142, 68, 173, 180]            # Crítico (Roxo)
    gdf['cor_declividade'] = gdf['declividade'].apply(cor_slope)

    # Estética das Bolhas PCD (Consistente com Altitude)
    min_pct, max_pct = gdf['Percentual de PCDs'].min(), gdf['Percentual de PCDs'].max()
    gdf['posicao_bolha'] = gdf.apply(lambda r: [r.geometry.centroid.x, r.geometry.centroid.y, (r['altitude'] * 0.2) + 2], axis=1)
    
    def calc_cor_tricolor(p):
        frac = (p - min_pct) / (max_pct - min_pct) if max_pct > min_pct else 0
        if frac < 0.33: return [255, 215, 0, 230]
        elif frac < 0.66: return [255, 140, 0, 230]
        else: return [211, 47, 47, 230]
    
    gdf['cor_pcd'] = gdf['Percentual de PCDs'].apply(calc_cor_tricolor)
    gdf['raio_bolha'] = gdf['Percentual de PCDs'].apply(lambda x: 12 + ((x - min_pct) / (max_pct - min_pct) * 38))
    
    return gdf

gdf_pcd = carregar_dados_completos()

# ==========================================
# 3. FILTROS E LÓGICA DE COR DINÂMICA
# ==========================================
with st.sidebar:
    valor_slider = st.slider(
        "Mostrar setores com mais de (% PCD):",
        float(gdf_pcd['Percentual de PCDs'].min()),
        float(gdf_pcd['Percentual de PCDs'].max()),
        float(gdf_pcd['Percentual de PCDs'].min()),
        format="%.2f%%"
    )

gdf_filtrado = gdf_pcd[gdf_pcd['Percentual de PCDs'] >= valor_slider]
coluna_cor_terreno = "cor_altitude" if modo_analise == "Hipsometria (Altitude)" else "cor_declividade"

# ==========================================
# 4. MAPA PYDECK (MULTI-CAMADA)
# ==========================================
st.markdown(f"### Maquete Interativa: {modo_analise}")

cor_linha = [80, 80, 80, 200] if basemap_pdk == "light" else [255, 255, 255, 120]

camada_terreno = pdk.Layer(
    "GeoJsonLayer", gdf_pcd, extruded=True, get_elevation="altitude", elevation_scale=0.2, 
    get_fill_color=coluna_cor_terreno, get_line_color=cor_linha, line_width_min_pixels=1.5, pickable=True,
)

camada_bolhas = pdk.Layer(
    "ScatterplotLayer", gdf_filtrado, get_position="posicao_bolha", get_radius="raio_bolha",
    radius_scale=1.1, get_fill_color="cor_pcd", 
    get_line_color=[40, 40, 40, 255] if basemap_pdk == "light" else [255, 255, 255, 255], 
    stroked=True, line_width_min_pixels=1.5, pickable=True, auto_highlight=True
)

st.pydeck_chart(pdk.Deck(
    layers=[camada_terreno, camada_bolhas],
    initial_view_state=pdk.ViewState(latitude=gdf_pcd.geometry.centroid.y.mean(), longitude=gdf_pcd.geometry.centroid.x.mean(), zoom=15.2, pitch=45, bearing=5),
    map_style=basemap_pdk,
    tooltip={"html": "<b>Setor:</b> {sub_bairro}<br><b>Altitude:</b> {altitude}m<br><b>Inclinação:</b> {declividade:.1f}%<br><b>PCD:</b> {Percentual de PCDs:.2f}%"}
))

# ==========================================
# 5. PAINEL ANALÍTICO (ADAPTATIVO)
# ==========================================
@st.fragment
def renderizar_graficos(df_final):
    st.divider()
    st.subheader("📊 Evidências Analíticas")
    if df_final.empty: return

    df_plot = pd.DataFrame(df_final.drop(columns=['geometry']))
    df_plot['Faixa de Relevo'] = pd.qcut(df_plot['altitude'], q=3, labels=['1. Baixo', '2. Médio', '3. Alto'])
    
    col1, col2 = st.columns(2)
    with col1:
        # Gráfico 1 alterna entre Altitude ou Declividade
        var_y = 'altitude' if modo_analise == "Hipsometria (Altitude)" else 'declividade'
        unidade = "m" if var_y == 'altitude' else "%"
        fig1 = px.line(df_plot.sort_values(var_y, ascending=False), x='sub_bairro', y=var_y, markers=True, title=f"Perfil de {modo_analise}")
        fig1.update_traces(line_color='#7f8c8d', marker=dict(color='#c0392b', size=8))
        fig1.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', xaxis_title=None, yaxis_title=unidade)
        st.plotly_chart(fig1, use_container_width=True)

    with col2:
        fig2 = px.bar(df_plot.sort_values('Percentual de PCDs', ascending=False), x='sub_bairro', y='Percentual de PCDs', title="Concentração de PCDs por Setor")
        fig2.update_traces(marker_color='#e67e22')
        fig2.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', xaxis_title=None, yaxis_title="%")
        st.plotly_chart(fig2, use_container_width=True)

    # --- DISPERSÃO E CONCLUSÃO (LÓGICA OURO PRESERVADA) ---
    st.markdown("#### Matriz de Correlação Clusterizada")
    fig3 = px.scatter(df_plot, x='altitude', y='Percentual de PCDs', color='Faixa de Relevo', size='Percentual de PCDs', hover_name='sub_bairro',
                      color_discrete_map={'1. Baixo': '#FFB300', '2. Médio': '#FF7F00', '3. Alto': '#D32F2F'},
                      title="Dispersão: Altitude vs Densidade PCD", labels={'altitude': 'Altitude (m)', 'Percentual de PCDs': 'PCDs (%)'})
    fig3.update_traces(marker=dict(line=dict(width=1, color='white')))
    fig3.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    st.plotly_chart(fig3, use_container_width=True)

    resumo = df_plot.groupby('Faixa de Relevo', observed=False)['Percentual de PCDs'].mean().reset_index()
    fig4 = go.Figure()
    fig4.add_trace(go.Scatter(
        x=resumo['Faixa de Relevo'], y=resumo['Percentual de PCDs'], mode='lines+markers+text',
        line=dict(color='#34495e', width=4, shape='spline'),
        marker=dict(size=24, color=['#FFB300', '#FF7F00', '#D32F2F'], line=dict(width=2, color='white')),
        text=resumo['Percentual de PCDs'].apply(lambda x: f"{x:.2f}%"), textposition="top center", textfont=dict(size=11) 
    ))
    fig4.update_layout(title="Conclusão: Tendência de Concentração por Nível de Terreno", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', yaxis_title="Média PCD (%)", xaxis_title="Nível do Terreno")
    st.plotly_chart(fig4, use_container_width=True)

renderizar_graficos(gdf_filtrado)
