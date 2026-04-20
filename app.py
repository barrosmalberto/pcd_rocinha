import streamlit as st
import pydeck as pdk
import pandas as pd
import geopandas as gpd
import numpy as np
import requests
import time
import plotly.graph_objects as go
import plotly.express as px

# --- Configuração Inicial ---
st.set_page_config(page_title="Rocinha PCD & Hipsometria", layout="wide")

# Barra lateral com a Legenda e o Filtro
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/814/814513.png", width=50) # Ícone decorativo
    st.markdown("### 📌 Legenda Analítica")
    st.markdown("Nesta maquete interativa, cruzamos duas variáveis espaciais:")
    st.markdown("---")
    st.markdown("🏢 **Terreno (Z):**<br>Representa a *Altitude Média* do bairro. Mais escuro e elevado = mais íngreme.", unsafe_allow_html=True)
    st.markdown("🎨 **Bolhas (Foco):**<br>Representa o *Percentual de PCDs* na população local.", unsafe_allow_html=True)
    st.markdown("🟡 **Amarelo/Pequeno:** Baixa Concentração")
    st.markdown("🔴 **Vermelho/Grande:** Alta Concentração")
    st.markdown("---")
    st.info("💡 **Dica de UX:** Segure o botão direito do rato e arraste para inclinar e girar o mapa 3D.")
    
    st.markdown("### 🎛️ Filtro Analítico")
    # O slider será configurado dinamicamente após carregarmos os dados

st.title("🏔️ Acesso Vertical: PCDs na Rocinha")

# --- Motor de Busca de Elevação (API) ---
@st.cache_data(show_spinner=False)
def obter_elevacao_lote(df, lat_col="lat", lon_col="lon", chunk_size=100):
    elevacoes = []
    locations = [{"latitude": row[lat_col], "longitude": row[lon_col]} for _, row in df.iterrows()]
    url = "https://api.open-elevation.com/api/v1/lookup"
    
    progresso = st.progress(0, text="🌍 A consultar API de Elevação do Terreno...")
    
    for i in range(0, len(locations), chunk_size):
        chunk = locations[i : i + chunk_size]
        payload = {"locations": chunk}
        try:
            response = requests.post(url, json=payload, timeout=20)
            if response.status_code == 200:
                resultados = response.json().get("results", [])
                elevacoes.extend([res["elevation"] for res in resultados])
            else:
                elevacoes.extend([0] * len(chunk))
        except Exception:
            elevacoes.extend([0] * len(chunk))
            
        time.sleep(1) # Respeito ao Rate Limit
        progresso.progress(min(1.0, (i + chunk_size) / len(locations)))
        
    progresso.empty()
    return elevacoes

# --- ETL Unificado: Base Subtil + Bolhas de PCD ---
@st.cache_data
def carregar_dados_completos():
    gdf = gpd.read_file("rocinha_pcds.geojson")
    if gdf.crs != "EPSG:4326":
        gdf = gdf.to_crs(epsg=4326)
        
    with st.spinner("🌍 A calcular hipsometria dos bairros..."):
        centroids = gdf.geometry.centroid
        temp_df = pd.DataFrame({'lat': centroids.y, 'lon': centroids.x})
        gdf['altitude'] = obter_elevacao_lote(temp_df)
    
    # 1. ESTÉTICA DO TERRENO (A Barreira)
    min_alt, max_alt = gdf['altitude'].min(), gdf['altitude'].max()
    def calcular_cor_terreno(alt):
        val = (alt - min_alt) / (max_alt - min_alt) if max_alt > min_alt else 0
        cinza = int(120 - (80 * val)) 
        return [cinza, cinza, cinza, 200]
    
    gdf['cor_terreno'] = gdf['altitude'].apply(calcular_cor_terreno)

    # 2. ESTÉTICA DOS PCDS (O Foco)
    min_pct, max_pct = gdf['PCDS — Planilha1_%'].min(), gdf['PCDS — Planilha1_%'].max()
    def calcular_cor_pcd(pct):
        val = (pct - min_pct) / (max_pct - min_pct) if max_pct > min_pct else 0
        return [255, int(255 * (1 - val)), 0, 230]

    gdf['cor_pcd'] = gdf['PCDS — Planilha1_%'].apply(calcular_cor_pcd)
    
    # Truque mágico: Bolha flutua 5 metros acima do chão
    gdf['posicao_bolha'] = gdf.apply(lambda r: [r.geometry.centroid.x, r.geometry.centroid.y, r['altitude'] + 5], axis=1)
    
    # Raio da bolha
    gdf['raio_bolha'] = gdf['PCDS — Planilha1_%'].apply(lambda x: 10 + ((x - min_pct) / (max_pct - min_pct) * 45) if max_pct > min_pct else 15)
    
    return gdf

# Executa o ETL
gdf_pcd = carregar_dados_completos()

# --- Configuração do Slider Dinâmico na Sidebar ---
with st.sidebar:
    min_val = float(gdf_pcd['PCDS — Planilha1_%'].min())
    max_val = float(gdf_pcd['PCDS — Planilha1_%'].max())
    
    filtro_pct = st.slider(
        "Ocultar áreas com densidade menor que:",
        min_value=min_val,
        max_value=max_val,
        value=min_val,
        format="%.4f"
    )

# Aplica o filtro APENAS na camada de bolhas (mantém o terreno completo)
gdf_bolhas_filtradas = gdf_pcd[gdf_pcd['PCDS — Planilha1_%'] >= filtro_pct]

# --- Renderização do Mapa: Terreno vs Bolhas PCD ---
st.markdown("### Mapa de Mobilidade: O Terreno como Barreira para PCDs")

camada_terreno = pdk.Layer(
    "GeoJsonLayer",
    gdf_pcd, # <-- O terreno usa o GDF completo
    extruded=True, 
    wireframe=True,
    get_elevation="altitude",
    elevation_scale=0.8,
    get_fill_color="cor_terreno",
    get_line_color=[255, 255, 255, 40],
    pickable=True,
)

camada_pcd = pdk.Layer(
    "ScatterplotLayer",
    gdf_bolhas_filtradas, # <-- As bolhas usam o GDF filtrado pelo slider!
    get_position="posicao_bolha",
    get_radius="raio_bolha",
    radius_scale=1.5,
    get_fill_color="cor_pcd",
    get_line_color=[255, 255, 255, 255], 
    stroked=True,
    line_width_min_pixels=1.5,
    pickable=True,
    auto_highlight=True
)

visao_inicial = pdk.ViewState(
    latitude=gdf_pcd.geometry.centroid.y.mean(),
    longitude=gdf_pcd.geometry.centroid.x.mean(),
    zoom=14.5, pitch=55, bearing=15
)

st.pydeck_chart(pdk.Deck(
    layers=[camada_terreno, camada_pcd], 
    initial_view_state=visao_inicial,
    map_style="dark",
    tooltip={
        "html": "<b>Setor:</b> {sub_bairro}<br/>"
                "<b>Altitude Média:</b> {altitude} m<br/>"
                "<b>PCDs mapeados:</b> {PCDS — Planilha1_Pessoas com Deficiência} pessoas<br/>"
                "<b>Densidade (Percentual):</b> {PCDS — Planilha1_%}"
    }
))

# --- Painel de Validação Analítica (Gráficos Direcionados) ---
@st.fragment
def painel_analitico(gdf_bolhas_filtradas):
    st.divider()
    st.subheader("📊 Painel de Validação de Hipótese")
    
    # Se o filtro remover todas as bolhas, interrompe a renderização dos gráficos
    if gdf_bolhas_filtradas.empty:
        st.warning("Nenhum setor atinge o critério do filtro atual. Reduza o valor no painel lateral.")
        return
        
    # Prepara o DataFrame para os gráficos (removemos a geometria)
    df_plot = pd.DataFrame(gdf_bolhas_filtradas.drop(columns=['geometry']))
    
    # --- GRÁFICO 1: Altitude por Área (Em Linha e Decrescente) ---
    df_alt = df_plot.sort_values(by='altitude', ascending=False)
    
    fig1 = go.Figure()
    fig1.add_trace(go.Scatter(
        x=df_alt['sub_bairro'], 
        y=df_alt['altitude'],
        mode='lines+markers',
        line=dict(color='gray', width=3),
        marker=dict(size=10, color='crimson'),
        name='Altitude'
    ))
    fig1.update_layout(
        title="1. Perfil Topográfico: Altitude Média por Setor (Ordem Decrescente)",
        xaxis_title="Setores da Rocinha",
        yaxis_title="Altitude (Metros)",
        xaxis_tickangle=-45,
        margin=dict(b=100)
    )
    
    # --- GRÁFICO 2: Percentual de PCDs por Área (Barras e Decrescente) ---
    df_pct = df_plot.sort_values(by='PCDS — Planilha1_%', ascending=False)
    
    fig2 = go.Figure()
    fig2.add_trace(go.Bar(
        x=df_pct['sub_bairro'], 
        y=df_pct['PCDS — Planilha1_%'],
        marker_color='darkorange',
        text=df_pct['PCDS — Planilha1_%'].apply(lambda x: f"{x*100:.2f}%"),
        textposition='outside'
    ))
    fig2.update_layout(
        title="2. Concentração: Percentual de PCDs por Setor (Ordem Decrescente)",
        xaxis_title="Setores da Rocinha",
        yaxis_title="Percentual de PCDs (%)",
        xaxis_tickangle=-45,
        margin=dict(b=100)
    )
    
    # --- GRÁFICO 3: Correlação Direta (Altitude x PCDs) ---
    fig3 = px.scatter(
        df_plot, 
        x='altitude', 
        y='PCDS — Planilha1_%',
        hover_name='sub_bairro',
        size='PCDS — Planilha1_%',
        color='altitude',
        color_continuous_scale='Reds',
        title="3. Matriz de Hipótese: Altitude vs Concentração de PCDs"
    )
    fig3.update_traces(marker=dict(line=dict(width=1, color='DarkSlateGrey')))
    fig3.update_layout(
        xaxis_title="Altitude (Metros)",
        yaxis_title="Percentual de PCDs (%)"
    )

    # Renderiza os três gráficos organizados na tela
    st.plotly_chart(fig1, use_container_width=True)
    st.plotly_chart(fig2, use_container_width=True)
    st.plotly_chart(fig3, use_container_width=True)

# Executa o painel com os dados filtrados
painel_analitico(gdf_bolhas_filtradas)
