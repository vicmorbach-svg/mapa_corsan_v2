import streamlit as st
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import plotly.express as px
import io
import requests
import time

st.set_page_config(page_title="Mapa de Diretorias - RS", layout="wide")

st.title("🗺️ Mapa de Infraestrutura e Diretorias - RS")

# --- FUNÇÕES DE CARREGAMENTO ---

@st.cache_data
def load_ibge_data():
    """Busca Domicílios, Água e Esgoto no IBGE com extração dinâmica e alertas"""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    colunas_seguranca = ['code_muni', 'Total_Domicilios', 'Cobertura_Agua_%', 'Cobertura_Esgoto_%']

    def extrair_dados(url, nome_valor):
        try:
            r = requests.get(url, headers=headers)
            if r.status_code != 200:
                st.warning(f"⚠️ Erro {r.status_code} ao buscar {nome_valor}. O IBGE pode ter bloqueado o acesso.")
                return pd.DataFrame(columns=['code_muni', nome_valor])

            dados = r.json()
            if len(dados) <= 1:
                st.warning(f"⚠️ O IBGE retornou uma tabela vazia para {nome_valor}. Verifique os parâmetros.")
                return pd.DataFrame(columns=['code_muni', nome_valor])

            # Descobre dinamicamente qual coluna contém o Código do Município
            cabecalho = dados[0]
            chave_muni = 'D1C' # Padrão caso não encontre
            for k, v in cabecalho.items():
                if v == "Município (Código)":
                    chave_muni = k
                    break

            df = pd.DataFrame([{'code_muni': i[chave_muni], nome_valor: i['V']} for i in dados[1:]])
            return df
        except Exception as e:
            st.warning(f"⚠️ Erro na requisição de {nome_valor}: {e}")
            return pd.DataFrame(columns=['code_muni', nome_valor])

        # 1. Domicílios (Tabela 4709) - Essa funcionou, mantemos igual
    url_dom = "https://apisidra.ibge.gov.br/values/t/4709/n6/all/v/93/p/2022"
    df_dom = extrair_dados(url_dom, 'Total_Domicilios')

    time.sleep(1.5) 

    # 2. Esgoto - Rede Geral (Tabela 9814)
    # Tática Força Bruta: Pedimos todas as variáveis (/v/all) e períodos (/p/all) para não dar Erro 400
    url_esgoto = "https://apisidra.ibge.gov.br/values/t/9814/n6/all/v/all/p/all/c11512/330245"
    df_esgoto = extrair_dados(url_esgoto, 'Domicilios_Esgoto')

    time.sleep(1.5) 

    # 3. Água - Rede Geral (Tabela 9813)
    # Tática Força Bruta: Pedimos todas as variáveis (/v/all) e períodos (/p/all)
    url_agua = "https://apisidra.ibge.gov.br/values/t/9813/n6/all/v/all/p/all/c11511/330227"
    df_agua = extrair_dados(url_agua, 'Domicilios_Agua')

    if df_dom.empty:
        return pd.DataFrame(columns=colunas_seguranca)

    # Junta todas as tabelas
    df_final = df_dom.merge(df_esgoto, on='code_muni', how='left').merge(df_agua, on='code_muni', how='left')

    # Limpeza e conversão de dados
    for col in ['Total_Domicilios', 'Domicilios_Esgoto', 'Domicilios_Agua']:
        if col in df_final.columns:
            # Converte para número e transforma valores nulos/erros em 0
            df_final[col] = pd.to_numeric(df_final[col], errors='coerce').fillna(0)

    # Evita erro de divisão por zero caso alguma cidade venha com 0 domicílios
    df_final['Total_Domicilios_Calc'] = df_final['Total_Domicilios'].replace(0, 1)

    # Calcula as porcentagens
    df_final['Cobertura_Esgoto_%'] = (df_final['Domicilios_Esgoto'] / df_final['Total_Domicilios_Calc']) * 100
    df_final['Cobertura_Agua_%'] = (df_final['Domicilios_Agua'] / df_final['Total_Domicilios_Calc']) * 100

    df_final['Cobertura_Esgoto_%'] = df_final['Cobertura_Esgoto_%'].round(1)
    df_final['Cobertura_Agua_%'] = df_final['Cobertura_Agua_%'].round(1)
    df_final['code_muni'] = df_final['code_muni'].astype(str)

    return df_final

@st.cache_data
def load_data():
    """Carrega o mapa e a planilha simples (sem clientes por enquanto)"""
    mapa = gpd.read_file("rs_municipios.geojson").to_crs(epsg=4326)
    mapa['code_muni'] = mapa['code_muni'].astype(str).str[:7] 

    df_raw = pd.read_excel("Reestruturaao_Oficial_1.xlsx")
    df_raw['CIDADE'] = df_raw['CIDADE'].astype(str).str.upper().str.strip()

    return mapa, df_raw

# --- EXECUÇÃO ---
with st.spinner("Baixando dados de infraestrutura do IBGE..."):
    rs_map, df_planilha = load_data()
    df_ibge = load_ibge_data()

# --- CRUZAMENTO ---
rs_map = rs_map.merge(df_ibge, on='code_muni', how='left')
rs_map['name_muni'] = rs_map['name_muni'].astype(str).str.upper().str.strip()

mapa_diretorias = rs_map.merge(df_planilha, how="left", left_on="name_muni", right_on="CIDADE")
mapa_diretorias['DIRETORIA'] = mapa_diretorias['DIRETORIA'].fillna('Sem Diretoria')

cidades_destaque = mapa_diretorias[mapa_diretorias['DIRETORIA'] != 'Sem Diretoria']

# --- CORES FIXAS ---
dicionario_cores = {'CENTRAL': '#FF9999', 'LESTE': '#66B2FF', 'NORTE': '#99FF99', 'OESTE': '#FFCC99', 'SUL': '#C2C2F0'}
diretorias_unicas = sorted(df_planilha['DIRETORIA'].dropna().unique())
abas = st.tabs(["📍 Mapa Interativo", "Visão Geral (Download)"] + diretorias_unicas)

# ==========================================
# ABA 0: MAPA INTERATIVO (PLOTLY)
# ==========================================
with abas[0]:
    st.subheader("Busca e Exploração Interativa")
    lista_cidades = sorted(cidades_destaque['name_muni'].unique())

    if 'cidade_selecionada' not in st.session_state:
        st.session_state.cidade_selecionada = None

    col1, col2 = st.columns([4, 1])
    with col1:
        nova_selecao = st.selectbox("🔍 Destaque uma cidade:", lista_cidades, index=None, placeholder="Escolha uma cidade...")
    with col2:
        st.write(""); st.write("")
        if st.button("🗑️ Limpar", use_container_width=True): nova_selecao = None 

    if nova_selecao != st.session_state.cidade_selecionada:
        st.session_state.cidade_selecionada = nova_selecao
        st.rerun()

    cidade_atual = st.session_state.cidade_selecionada
    mapa_interativo = mapa_diretorias.copy()
    mapa_zoom, mapa_centro = 5.5, {"lat": -30.0, "lon": -53.5}

    if cidade_atual is None:
        mapa_interativo['Status_Cor'] = mapa_interativo['DIRETORIA']
        cores_plotly = dicionario_cores.copy()
        cores_plotly['Sem Diretoria'] = '#E0E0E0'
    else:
        regional_alvo = mapa_interativo[mapa_interativo['name_muni'] == cidade_atual]['DIRETORIA'].values[0]
        mapa_interativo['Status_Cor'] = mapa_interativo.apply(lambda row: '📍 Selecionada' if row['name_muni'] == cidade_atual else (f'Regional: {regional_alvo}' if row['DIRETORIA'] == regional_alvo else 'Outras'), axis=1)
        cores_plotly = {'📍 Selecionada': '#FF0000', f'Regional: {regional_alvo}': dicionario_cores[regional_alvo], 'Outras': '#F0F0F0'}
        centroide = mapa_interativo[mapa_interativo['name_muni'] == cidade_atual].geometry.iloc[0].centroid
        mapa_centro, mapa_zoom = {"lat": centroide.y, "lon": centroide.x}, 8.0

    mapa_interativo = mapa_interativo.set_index('name_muni')

    # Configuração do Balãozinho de Informações (Agora com Água e Esgoto)
    hover_config = {
        'DIRETORIA': True, 
        'Status_Cor': False, 
        'Total_Domicilios': ':.0f', 
        'Cobertura_Agua_%': ':.1f',
        'Cobertura_Esgoto_%': ':.1f'
    }

    fig_interativa = px.choropleth_mapbox(
        mapa_interativo, geojson=mapa_interativo.geometry, locations=mapa_interativo.index,
        color='Status_Cor', color_discrete_map=cores_plotly, mapbox_style="carto-positron",
        zoom=mapa_zoom, center=mapa_centro, opacity=0.8, hover_name=mapa_interativo.index,
        hover_data=hover_config, height=750
    )
    fig_interativa.update_layout(margin={"r":0,"t":0,"l":0,"b":0})
    st.plotly_chart(fig_interativa, use_container_width=True)

# ==========================================
# FUNÇÕES DE DOWNLOAD (MATPLOTLIB)
# ==========================================
def criar_figura_mapa_completo(rs_map, cidades_destaque, dicionario_cores, diretoria_especifica=None):
    fig, ax = plt.subplots(figsize=(12, 10))
    rs_map.plot(ax=ax, color='#e0e0e0', edgecolor='white', linewidth=0.5)
    itens_legenda = []
    if diretoria_especifica is None:
        for diretoria, cor in dicionario_cores.items():
            subset = cidades_destaque[cidades_destaque['DIRETORIA'] == diretoria]
            if not subset.empty:
                subset.plot(ax=ax, color=cor, edgecolor='black', linewidth=0.8)
                itens_legenda.append(mpatches.Patch(color=cor, label=diretoria))
        ax.legend(handles=itens_legenda, title='Diretorias', loc='lower right')
    else:
        cor = dicionario_cores[diretoria_especifica]
        subset = cidades_destaque[cidades_destaque['DIRETORIA'] == diretoria_especifica]
        if not subset.empty:
            subset.plot(ax=ax, color=cor, edgecolor='black', linewidth=0.8)
            itens_legenda.append(mpatches.Patch(color=cor, label=diretoria_especifica))
        ax.legend(handles=itens_legenda, title='Diretoria', loc='lower right')
    ax.axis('off'); fig.tight_layout()
    return fig

def criar_figura_mapa_limpo(rs_map, cidades_destaque, dicionario_cores, diretoria_especifica=None):
    fig, ax = plt.subplots(figsize=(12, 10))
    fig.subplots_adjust(left=0, right=1, bottom=0, top=1)
    rs_map.plot(ax=ax, color='#e0e0e0', edgecolor='white', linewidth=0.5)
    if diretoria_especifica is None:
        for diretoria, cor in dicionario_cores.items():
            subset = cidades_destaque[cidades_destaque['DIRETORIA'] == diretoria]
            if not subset.empty: subset.plot(ax=ax, color=cor, edgecolor='black', linewidth=0.8)
    else:
        cor = dicionario_cores[diretoria_especifica]
        subset = cidades_destaque[cidades_destaque['DIRETORIA'] == diretoria_especifica]
        if not subset.empty: subset.plot(ax=ax, color=cor, edgecolor='black', linewidth=0.8)
    ax.axis('off'); ax.margins(0)
    return fig

def gerar_buffer_download(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=300, bbox_inches='tight', pad_inches=0, transparent=True)
    buf.seek(0)
    return buf

with abas[1]:
    with st.spinner("Gerando mapas..."):
        fig_geral_completo = criar_figura_mapa_completo(rs_map, cidades_destaque, dicionario_cores)
        fig_geral_limpo = criar_figura_mapa_limpo(rs_map, cidades_destaque, dicionario_cores)
        st.pyplot(fig_geral_completo)
        col1, col2 = st.columns(2)
        with col1: st.download_button("📥 Baixar Mapa (Com Legenda)", data=gerar_buffer_download(fig_geral_completo), file_name="mapa_geral.png", mime="image/png", use_container_width=True)
        with col2: st.download_button("📥 Baixar Mapa (Apenas Contorno)", data=gerar_buffer_download(fig_geral_limpo), file_name="mapa_geral_limpo.png", mime="image/png", use_container_width=True)

for i, diretoria in enumerate(diretorias_unicas):
    with abas[i + 2]:
        with st.spinner(f"Gerando mapas da regional {diretoria}..."):
            fig_ind_completo = criar_figura_mapa_completo(rs_map, cidades_destaque, dicionario_cores, diretoria_especifica=diretoria)
            fig_ind_limpo = criar_figura_mapa_limpo(rs_map, cidades_destaque, dicionario_cores, diretoria_especifica=diretoria)
            st.pyplot(fig_ind_completo)
            col1, col2 = st.columns(2)
            with col1: st.download_button(f"📥 Baixar Mapa {diretoria} (Com Legenda)", data=gerar_buffer_download(fig_ind_completo), file_name=f"mapa_{diretoria.lower()}.png", mime="image/png", use_container_width=True)
            with col2: st.download_button(f"📥 Baixar Mapa {diretoria} (Apenas Contorno)", data=gerar_buffer_download(fig_ind_limpo), file_name=f"mapa_{diretoria.lower()}_limpo.png", mime="image/png", use_container_width=True)
