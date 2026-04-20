import streamlit as st
import pydeck as pdk
import pandas as pd
import geopandas as gpd
import numpy as np
import requests
import time
import plotly.graph_objects as go

# --- Configuração Inicial ---
st.set_page_config(page_title="Rocinha PCD & Hipsometria", layout="wide")
st.title("🏔️ Acesso Vertical: PCDs na Rocinha")

# --- Motor de Busca de Elevação (API) ---
@st.cache_data(show_spinner=False)
def obter_elevacao_lote(df, lat_col="lat", lon_col="lon", chunk_size=100):
    elevacoes = []
    locations = [{"latitude": row[lat_col], "longitude": row[lon_col]} for _, row in df.iterrows()]
    url = "https://api.open-elevation.com/api/v1/lookup"
    
    progresso = st.progress(0, text="🌍 Consultando API de Elevação do Terreno...")
    
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

# --- ETL: Leitura do GeoJSON e Enriquecimento ---
@st.cache_data
def carregar_dados_reais():
    # 1. Lê o GeoJSON que você fez upload
    gdf = gpd.read_file("rocinha_pcds.geojson")
    
    # 2. Converte para Lat/Lon (EPSG:4326) exigido pelo PyDeck
    if gdf.crs != "EPSG:4326":
        gdf = gdf.to_crs(epsg=4326)
        
    # 3. Como são polígonos, pegamos o centroide (ponto central) para os postes 3D
    gdf['centroid'] = gdf.geometry.centroid
    gdf['lon'] = gdf['centroid'].x
    gdf['lat'] = gdf['centroid'].y
    
    # Converte para DataFrame do Pandas (mais leve)
    df_pcd = pd.DataFrame(gdf.drop(columns='geometry'))
    
    # 4. Busca as altitudes na API usando as latitudes e longitudes reais
    with st.spinner("Mapeando elevação exata das residências..."):
        df_pcd['altitude'] = obter_elevacao_lote(df_pcd)
        
    # 5. Criação de cor dinâmica (Azul = Baixo, Vermelho = Alto)
    max_alt = df_pcd['altitude'].max() if df_pcd['altitude'].max() > 0 else 1
    df_pcd['cor'] = df_pcd['altitude'].apply(
        lambda x: [int(255 * (x / max_alt)), 0, int(255 * (1 - (x / max_alt))), 200]
    )
    
    # --- GERAÇÃO DE GRADE FAKE DA ROCINHA PARA COMPARAÇÃO ---
    # Como não temos os dados de *todos* os habitantes, geramos uma grade de relevo para a média
    lon_min, lat_min, lon_max, lat_max = gdf.total_bounds
    df_grade = pd.DataFrame({
        "lat": np.random.uniform(lat_min, lat_max, 500),
        "lon": np.random.uniform(lon_min, lon_max, 500)
    })
    df_grade['altitude'] = obter_elevacao_lote(df_grade)
    
    return df_pcd, df_grade

# Carrega os dados
df_pcd, df_grade = carregar_dados_reais()

# --- Renderização do Mapa PyDeck ---
st.markdown("### Mapa Hipsométrico 3D: Localização de PCDs")

camada_terreno = pdk.Layer(
    "HeatmapLayer",
    data=df_grade,
    get_position=["lon", "lat"],
    get_weight="altitude",
    opacity=0.3,
    aggregation="MEAN"
)

# A altura da coluna é a altitude. O extrude liga o 3D.
camada_pcd = pdk.Layer(
    "ColumnLayer",
    data=df_pcd,
    get_position=["lon", "lat"],
    get_elevation="altitude",
    elevation_scale=3, # Exagero vertical
    radius=20,
    get_fill_color="cor",
    extruded=True,
    pickable=True,
    auto_highlight=True
)

# Foca o mapa na média das coordenadas da Rocinha
centro_lat = df_pcd['lat'].mean()
centro_lon = df_pcd['lon'].mean()

visao_inicial = pdk.ViewState(
    latitude=centro_lat, longitude=centro_lon, zoom=14.5, pitch=60, bearing=30
)

st.pydeck_chart(pdk.Deck(
    layers=[camada_terreno, camada_pcd], 
    initial_view_state=visao_inicial, 
    map_style="dark",
    tooltip={"text": "Bairro: {sub_bairro}\nAltitude: {altitude} m\nPCDs no local: {PCDS — Planilha1_Pessoas com Deficiência}"}
))

st.divider()

# --- Painel de Validação Analítica ---
@st.fragment
def painel_analitico(df_pcd, df_grade):
    st.subheader("📊 Validação de Hipótese: Desigualdade de Acesso Vertical")
    
    m1, m2 = st.columns(2)
    media_favela = df_grade['altitude'].mean()
    media_pcd = df_pcd['altitude'].mean()
    
    m1.metric("Altitude Média (Terreno Geral)", f"{media_favela:.1f} m")
    m2.metric("Altitude Média (PCDs)", f"{media_pcd:.1f} m", delta=f"{(media_pcd - media_favela):.1f} m vs Média")
    
    fig = go.Figure()
    fig.add_trace(go.Histogram(x=df_grade['altitude'], name='Relevo Geral', marker_color='gray', opacity=0.5, histnorm='probability'))
    fig.add_trace(go.Histogram(x=df_pcd['altitude'], name='Residências PCD', marker_color='crimson', opacity=0.7, histnorm='probability'))
    
    fig.update_layout(barmode='overlay', title_text="Distribuição por Faixa de Altitude", xaxis_title_text='Altitude (Metros)')
    st.plotly_chart(fig, use_container_width=True)

painel_analitico(df_pcd, df_grade)
