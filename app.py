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
    st.markdown("🏢 **Terreno (Z):**<br>Representa a *Altitude Média* do bairro. Mais escuro e elevado = mais íngreme.", unsafe_allow_html=True)
    st.markdown("🎨 **Bolhas (Foco):**<br>Representa o *Percentual de PCDs* na população local.", unsafe_allow_html=True)
    st.markdown("🟡 **Amarelo/Pequeno:** Baixa Concentração")
    st.markdown("🔴 **Vermelho/Grande:** Alta Concentração")
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

# --- ETL Unificado: Base Sutil + Bolhas de PCD ---
@st.cache_data
def carregar_dados_completos():
    gdf = gpd.read_file("rocinha_pcds.geojson")
    if gdf.crs != "EPSG:4326":
        gdf = gdf.to_crs(epsg=4326)
        
    with st.spinner("🌍 Calculando hipsometria dos bairros..."):
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
    
    # 3. GERAÇÃO DE GRADE PARA HISTOGRAMA
    with st.spinner("⛰️ Mapeando relevo base geral da favela..."):
        lon_min, lat_min, lon_max, lat_max = gdf.total_bounds
        df_grade = pd.DataFrame({
            "lat": np.random.uniform(lat_min, lat_max, 500),
            "lon": np.random.uniform(lon_min, lon_max, 500)
        })
        df_grade['altitude'] = obter_elevacao_lote(df_grade)
    
    return gdf, df_grade

gdf_pcd, df_grade = carregar_dados_completos()

# --- FILTRO DINÂMICO NA SIDEBAR ---
with st.sidebar:
    st.markdown("### 🎛️ Filtro Analítico")
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

st.divider()

# --- Painel de Validação Analítica ---
@st.fragment
def painel_analitico(gdf_bolhas_filtradas, df_grade):
    st.subheader("📊 Validação de Hipótese: Desigualdade de Acesso Vertical")
    
    # Se o filtro remover todas as bolhas, evitamos erro de divisão por zero
    if gdf_bolhas_filtradas.empty:
        st.warning("Nenhum setor atinge esse critério de filtro. Reduza o valor no painel lateral.")
        return
        
    m1, m2 = st.columns(2)
    media_favela = df_grade['altitude'].mean()
    media_pcd = gdf_bolhas_filtradas['altitude'].mean() # Média dinâmica que muda com o slider
    
    m1.metric("Altitude Média (Terreno Geral)", f"{media_favela:.1f} m")
    m2.metric("Altitude Média (Setores Filtrados)", f"{media_pcd:.1f} m", delta=f"{(media_pcd - media_favela):.1f} m vs Média")
    
    fig = go.Figure()
    fig.add_trace(go.Histogram(x=df_grade['altitude'], name='Relevo Geral', marker_color='gray', opacity=0.5, histnorm='probability'))
    fig.add_trace(go.Histogram(x=gdf_bolhas_filtradas['altitude'], name='Setores PCD', marker_color='crimson', opacity=0.7, histnorm='probability'))
    
    fig.update_layout(
        barmode='overlay', 
        title_text="Distribuição por Faixa de Altitude", 
        xaxis_title_text='Altitude (Metros)',
        yaxis_title_text='Probabilidade'
    )
    st.plotly_chart(fig, use_container_width=True)

# Passamos a versão filtrada para que o Histograma e as Métricas também atualizem dinamicamente!
painel_analitico(gdf_bolhas_filtradas, df_grade)
