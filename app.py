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

# Barra lateral com a Legenda
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/814/814513.png", width=50) # Ícone decorativo
    st.markdown("### 📌 Legenda Analítica")
    st.markdown("Nesta maquete interativa, cruzamos duas variáveis espaciais:")
    st.markdown("---")
    st.markdown("🏢 **Altura do Bloco (Z):**<br>Representa a *Altitude Média* do bairro. Quanto mais alto o bloco sobe na tela, mais íngreme e de difícil acesso é a área.", unsafe_allow_html=True)
    st.markdown("🎨 **Cor do Bloco (RGB):**<br>Representa o *Percentual de PCDs* na população local.", unsafe_allow_html=True)
    st.markdown("🟡 **Amarelo:** Baixa Concentração")
    st.markdown("🟠 **Laranja:** Média Concentração")
    st.markdown("🔴 **Vermelho Escuro:** Alta Concentração")
    st.markdown("---")
    st.info("💡 **Dica de UX:** Segure o botão direito do mouse e arraste para inclinar e girar o mapa 3D.")

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

# --- ETL Unificado: GeoJSON Coroplético + Grade Base ---
@st.cache_data
def carregar_dados_completos():
    # 1. Lê o GeoJSON real
    gdf = gpd.read_file("rocinha_pcds.geojson")
    if gdf.crs != "EPSG:4326":
        gdf = gdf.to_crs(epsg=4326)
        
    # 2. Busca altitude pelo centroide para erguer os bairros
    with st.spinner("🌍 Calculando hipsometria dos bairros..."):
        centroids = gdf.geometry.centroid
        temp_df = pd.DataFrame({'lat': centroids.y, 'lon': centroids.x})
        gdf['altitude'] = obter_elevacao_lote(temp_df)
    
    # 3. Normalização de Cores bivariada (Amarelo para Vermelho)
    min_pct = gdf['PCDS — Planilha1_%'].min()
    max_pct = gdf['PCDS — Planilha1_%'].max()

    def calcular_cor_pcd(pct):
        val = (pct - min_pct) / (max_pct - min_pct) if max_pct > min_pct else 0
        return [int(255 - (75 * val)), int(255 * (1 - val)), 0, 210]

    gdf['fill_color'] = gdf['PCDS — Planilha1_%'].apply(calcular_cor_pcd)
    
    # 4. GERAÇÃO DE GRADE DO TERRENO PARA VALIDAÇÃO ESTATÍSTICA (Histograma)
    with st.spinner("⛰️ Mapeando relevo base geral da favela..."):
        lon_min, lat_min, lon_max, lat_max = gdf.total_bounds
        df_grade = pd.DataFrame({
            "lat": np.random.uniform(lat_min, lat_max, 500),
            "lon": np.random.uniform(lon_min, lon_max, 500)
        })
        df_grade['altitude'] = obter_elevacao_lote(df_grade)
    
    return gdf, df_grade

# Executa o ETL
gdf_pcd, df_grade = carregar_dados_completos()

# --- Renderização do Mapa Coroplético 3D ---
st.markdown("### Maquete Analítica: Altitude vs. Concentração de PCDs")

camada_bairros = pdk.Layer(
    "GeoJsonLayer",
    gdf_pcd,
    extruded=True, # Liga o efeito 3D
    wireframe=True,
    get_elevation="altitude",
    elevation_scale=4, # Exagero vertical para as ladeiras
    get_fill_color="fill_color",
    get_line_color=[255, 255, 255, 80],
    pickable=True,
    auto_highlight=True
)

visao_inicial = pdk.ViewState(
    latitude=gdf_pcd.geometry.centroid.y.mean(),
    longitude=gdf_pcd.geometry.centroid.x.mean(),
    zoom=14.5,
    pitch=65, # Câmera inclinada para ver as alturas
    bearing=20
)

st.pydeck_chart(pdk.Deck(
    layers=[camada_bairros], 
    initial_view_state=visao_inicial,
    map_style="dark",
    tooltip={
        "html": "<b>Setor:</b> {sub_bairro}<br/>"
                "<b>Altitude Média:</b> {altitude} m<br/>"
                "<b>PCDs mapeados:</b> {PCDS — Planilha1_Pessoas com Deficiência} pessoas<br/>"
                "<b>Densidade (Percentual):</b> {PCDS — Planilha1_%}"
    }
))

st.divider()

# --- Painel de Validação Analítica ---
@st.fragment
def painel_analitico(gdf_pcd, df_grade):
    st.subheader("📊 Validação de Hipótese: Desigualdade de Acesso Vertical")
    
    m1, m2 = st.columns(2)
    media_favela = df_grade['altitude'].mean()
    media_pcd = gdf_pcd['altitude'].mean() # Agora puxamos do GDF dos bairros
    
    m1.metric("Altitude Média (Terreno Geral)", f"{media_favela:.1f} m")
    m2.metric("Altitude Média (Setores PCD)", f"{media_pcd:.1f} m", delta=f"{(media_pcd - media_favela):.1f} m vs Média")
    
    fig = go.Figure()
    fig.add_trace(go.Histogram(x=df_grade['altitude'], name='Relevo Geral', marker_color='gray', opacity=0.5, histnorm='probability'))
    fig.add_trace(go.Histogram(x=gdf_pcd['altitude'], name='Setores PCD', marker_color='crimson', opacity=0.7, histnorm='probability'))
    
    fig.update_layout(
        barmode='overlay', 
        title_text="Distribuição por Faixa de Altitude", 
        xaxis_title_text='Altitude (Metros)',
        yaxis_title_text='Probabilidade'
    )
    st.plotly_chart(fig, use_container_width=True)

painel_analitico(gdf_pcd, df_grade)
