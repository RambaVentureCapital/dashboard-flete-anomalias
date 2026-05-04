"""
Dashboard de Detección de Anomalías en Flete v3
================================================
Análisis estadístico POR CLIENTE (no global) - igual que la hoja
"Saltos abruptos flete" del Excel original.

CRITERIO DE DETECCIÓN:
Una anomalía es un registro donde el flete pagado se desvía
significativamente de la media histórica DEL MISMO CLIENTE,
considerando si el cambio se justifica o no por el volumen.

INSTALACIÓN:
    pip install streamlit pandas numpy plotly openpyxl

EJECUCIÓN:
    streamlit run dashboard_anomalias_v3.py
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ============================================================
# CONFIGURACIÓN DE LA PÁGINA
# ============================================================
st.set_page_config(
    page_title="Anomalías de Flete por Cliente",
    page_icon="🚚",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Estilos CSS personalizados
st.markdown("""
<style>
    .main { padding-top: 1rem; }
    .stMetric {
        background: linear-gradient(135deg, #1E3A8A 0%, #1E40AF 100%);
        padding: 20px;
        border-radius: 16px;
        color: white;
        box-shadow: 0 4px 12px rgba(30, 58, 138, 0.2);
    }
    .stMetric label { color: #BFDBFE !important; font-size: 13px !important; }
    .stMetric [data-testid="stMetricValue"] { color: white !important; font-size: 36px !important; }
    .stMetric [data-testid="stMetricDelta"] { color: #DBEAFE !important; }

    h1 { color: #0F172A; }
    h2 { color: #1E293B; border-bottom: 2px solid #1E3A8A; padding-bottom: 8px; }
    h3 { color: #334155; }

    .severidad-alto {
        background: linear-gradient(135deg, #DC2626 0%, #991B1B 100%);
        color: white !important;
        padding: 12px 20px;
        border-radius: 12px;
        font-weight: 600;
        margin: 4px 0;
    }
    .severidad-medio {
        background: linear-gradient(135deg, #F59E0B 0%, #B45309 100%);
        color: white !important;
        padding: 12px 20px;
        border-radius: 12px;
        font-weight: 600;
        margin: 4px 0;
    }
</style>
""", unsafe_allow_html=True)


# ============================================================
# CARGA DE DATOS
# ============================================================
@st.cache_data
def cargar_datos(ruta_archivo, nombre_hoja="Logistica Nac"):
    """Carga los datos del Excel desde la hoja Logistica Nac."""
    try:
        df = pd.read_excel(ruta_archivo, sheet_name=nombre_hoja, header=3)
    except Exception:
        df = pd.read_excel(ruta_archivo, sheet_name=nombre_hoja)

    # Limpiar nombres de columnas (quitar espacios al final)
    df.columns = [str(c).strip() for c in df.columns]

    # Convertir tipos
    if 'Fecha Factura' in df.columns:
        df['Fecha Factura'] = pd.to_datetime(df['Fecha Factura'], errors='coerce')

    cols_numericas = ['Flete', 'Litros Fact', 'Litros Rem', 'Total Flete', 'CXL']
    for col in cols_numericas:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    # Filtrar filas válidas
    df = df.dropna(subset=['Fecha Factura', 'Nombre de Cliente'])
    df = df[df['Flete'].notna() & (df['Flete'] > 0)]
    df = df[df['Litros Fact'].notna() & (df['Litros Fact'] > 0)]

    return df


# ============================================================
# DETECCIÓN DE ANOMALÍAS POR CLIENTE
# ============================================================
def detectar_anomalias_por_cliente(df, umbral_z_alto=2.0, umbral_z_medio=1.5, min_registros=3):
    """
    Detecta anomalías comparando cada registro contra la media histórica
    del MISMO CLIENTE.

    Replica el criterio de la hoja "Saltos abruptos flete":
    - Calcula media y desviación POR CLIENTE de Flete, Litros y CxL
    - Calcula Z-scores individuales
    - Clasifica severidad según Z-scores combinados
    - Genera diagnóstico textual

    Parámetros:
    - umbral_z_alto: umbral para clasificar como ALTO (default 2.0σ)
    - umbral_z_medio: umbral para clasificar como MEDIO (default 1.5σ)
    - min_registros: mínimo de registros por cliente para evaluar (default 3)
    """
    df = df.copy()
    df['Costo por Litro'] = df['Flete'] / df['Litros Fact']

    # Calcular estadísticas por cliente
    stats_cliente = df.groupby('Nombre de Cliente').agg(
        Flete_media=('Flete', 'mean'),
        Flete_std=('Flete', 'std'),
        Litros_media=('Litros Fact', 'mean'),
        Litros_std=('Litros Fact', 'std'),
        CxL_media=('Costo por Litro', 'mean'),
        CxL_std=('Costo por Litro', 'std'),
        Num_registros=('Flete', 'count')
    ).reset_index()

    # Merge stats al dataframe
    df = df.merge(stats_cliente, on='Nombre de Cliente', how='left')

    # Calcular Z-scores (manejo de división por 0)
    df['Z_Flete'] = np.where(
        df['Flete_std'] > 0,
        (df['Flete'] - df['Flete_media']) / df['Flete_std'],
        0
    )
    df['Z_Litros'] = np.where(
        df['Litros_std'] > 0,
        (df['Litros Fact'] - df['Litros_media']) / df['Litros_std'],
        0
    )
    df['Z_CxL'] = np.where(
        df['CxL_std'] > 0,
        (df['Costo por Litro'] - df['CxL_media']) / df['CxL_std'],
        0
    )

    # Clasificar severidad
    # Criterio: enfocarse en SALTOS AL ALZA del Costo por Litro (Z_CxL positivo)
    # ALTO: CxL muy elevado Y volumen NO lo justifica (Z_Litros bajo)
    # MEDIO: CxL elevado pero el volumen también explica parte
    def clasificar(row):
        # Solo evaluar si el cliente tiene suficientes registros
        if row['Num_registros'] < min_registros:
            return 'INSUFICIENTE'

        z_flete = row['Z_Flete']
        z_litros = row['Z_Litros']
        z_cxl = row['Z_CxL']

        # Solo nos interesan saltos al ALZA en costo por litro
        # (un flete que baja no es problema, lo grave es pagar más caro)
        if z_cxl < umbral_z_medio:
            return 'NORMAL'

        # ALTO: CxL muy alto Y (flete muy alto O litros NO justifican)
        # Es decir: pagamos mucho más caro sin explicación de volumen
        if z_cxl >= umbral_z_alto and (z_flete >= umbral_z_alto or z_litros < 0.5):
            return 'ALTO'

        # MEDIO: CxL elevado (entre medio y alto)
        if z_cxl >= umbral_z_medio:
            return 'MEDIO'

        return 'NORMAL'

    df['Severidad'] = df.apply(clasificar, axis=1)

    # Es anomalía si severidad es ALTO o MEDIO
    df['Es Anomalía'] = df['Severidad'].isin(['ALTO', 'MEDIO']).astype(int)

    # Generar diagnóstico
    def generar_diagnostico(row):
        if row['Severidad'] == 'NORMAL':
            return ''
        if row['Severidad'] == 'INSUFICIENTE':
            return f'⚪ Cliente con pocos registros ({int(row["Num_registros"])}) - no evaluable'

        z_flete = row['Z_Flete']
        z_litros = row['Z_Litros']
        z_cxl = row['Z_CxL']

        sign_flete = '+' if z_flete > 0 else ''
        sign_litros = '+' if z_litros > 0 else ''
        sign_cxl = '+' if z_cxl > 0 else ''

        if row['Severidad'] == 'ALTO':
            if abs(z_litros) < 1:  # Litros normales pero flete alto
                return (f'🔴 FLETE atípico ({sign_flete}{z_flete:.1f}σ vs media cliente '
                        f'${row["Flete_media"]:,.0f}) SIN salto proporcional en LITROS '
                        f'({sign_litros}{z_litros:.1f}σ). CxL ${row["Costo por Litro"]:.2f} '
                        f'vs media ${row["CxL_media"]:.2f} ({sign_cxl}{z_cxl:.1f}σ). '
                        f'Probable error o cargo no justificado — REVISAR.')
            else:
                return (f'🔴 FLETE atípico ({sign_flete}{z_flete:.1f}σ) y CxL elevado '
                        f'({sign_cxl}{z_cxl:.1f}σ vs media cliente). REVISAR.')
        else:  # MEDIO
            return (f'🟡 FLETE alto ({sign_flete}{z_flete:.1f}σ) y litros '
                    f'{"también altos" if abs(z_litros) > 0.5 else "normales"} '
                    f'({sign_litros}{z_litros:.1f}σ); CxL elevado ({sign_cxl}{z_cxl:.1f}σ). '
                    f'Verificar.')

    df['Diagnóstico'] = df.apply(generar_diagnostico, axis=1)

    return df


# ============================================================
# SIDEBAR — CONFIGURACIÓN
# ============================================================
st.sidebar.title("⚙️ Configuración")

archivo = st.sidebar.file_uploader(
    "📁 Sube tu archivo Excel",
    type=['xlsx', 'xls'],
    help="Archivo con la hoja 'Logistica Nac'"
)

if archivo is None:
    st.title("🚚 Dashboard de Anomalías de Flete por Cliente")
    st.warning("Por favor, sube el archivo Excel desde la barra lateral para visualizar el dashboard.")

    with st.expander("ℹ️ ¿Qué hace este dashboard?"):
        st.markdown("""
        Detecta cuándo el flete pagado a un cliente se sale de su patrón histórico:

        ### Criterios estadísticos:
        - **Z-Flete**: ¿Cuánto se desvía el flete vs la media de ESE cliente?
        - **Z-Litros**: ¿Cuánto se desvía el volumen vs su patrón normal?
        - **Z-CxL**: ¿El costo por litro está fuera de lo normal?

        ### Severidad:
        - 🔴 **ALTO**: Flete y CxL atípicos (>2σ). Probable error o cargo injustificado.
        - 🟡 **MEDIO**: Flete y CxL elevados (>1.5σ). Requiere verificación.
        - ⚪ **NORMAL**: Dentro del patrón histórico del cliente.

        ### Diferencia clave vs análisis global:
        Una anomalía NO es comparar contra el promedio de TODOS los clientes,
        sino contra el patrón histórico DEL MISMO cliente.
        Un cliente que normalmente paga $100,000 de flete tiene un comportamiento
        diferente a uno que paga $5,000 — cada uno se evalúa por separado.
        """)
    st.stop()

try:
    df_raw = cargar_datos(archivo)
except Exception as e:
    st.error(f"Error al cargar el archivo: {e}")
    st.stop()

# Verificar columnas necesarias
columnas_necesarias = ['Fecha Factura', 'Flete', 'Litros Fact', 'Nombre de Cliente']
faltantes = [c for c in columnas_necesarias if c not in df_raw.columns]
if faltantes:
    st.error(f"Faltan columnas en el archivo: {faltantes}")
    st.write("Columnas encontradas:", list(df_raw.columns))
    st.stop()

# ============================================================
# PARÁMETROS
# ============================================================
st.sidebar.markdown("### 📊 Umbrales de detección")

umbral_alto = st.sidebar.slider(
    "Umbral ALTO (σ)",
    min_value=1.5, max_value=3.5, value=2.0, step=0.1,
    help="Z-score para clasificar como anomalía ALTA"
)

umbral_medio = st.sidebar.slider(
    "Umbral MEDIO (σ)",
    min_value=1.0, max_value=2.5, value=1.5, step=0.1,
    help="Z-score para clasificar como anomalía MEDIA"
)

min_registros = st.sidebar.slider(
    "Mínimo registros por cliente",
    min_value=2, max_value=10, value=3,
    help="Clientes con menos registros no se evalúan (no hay suficiente historia)"
)

# Calcular anomalías
df = detectar_anomalias_por_cliente(df_raw, umbral_alto, umbral_medio, min_registros)

# ============================================================
# FILTROS
# ============================================================
st.sidebar.markdown("### 🔍 Filtros")
clientes = sorted(df['Nombre de Cliente'].dropna().unique())
cliente_sel = st.sidebar.multiselect("Cliente", options=clientes, default=[])

fecha_min = df['Fecha Factura'].min().date()
fecha_max = df['Fecha Factura'].max().date()
rango_fechas = st.sidebar.date_input(
    "Rango de fechas",
    value=(fecha_min, fecha_max),
    min_value=fecha_min,
    max_value=fecha_max
)

severidad_sel = st.sidebar.multiselect(
    "Severidad",
    options=['ALTO', 'MEDIO', 'NORMAL', 'INSUFICIENTE'],
    default=[],
    help="Vacío = todas las severidades"
)

# Aplicar filtros
df_filtrado = df.copy()
if cliente_sel:
    df_filtrado = df_filtrado[df_filtrado['Nombre de Cliente'].isin(cliente_sel)]
if isinstance(rango_fechas, tuple) and len(rango_fechas) == 2:
    df_filtrado = df_filtrado[
        (df_filtrado['Fecha Factura'].dt.date >= rango_fechas[0]) &
        (df_filtrado['Fecha Factura'].dt.date <= rango_fechas[1])
        ]
if severidad_sel:
    df_filtrado = df_filtrado[df_filtrado['Severidad'].isin(severidad_sel)]

# ============================================================
# HEADER
# ============================================================
st.title("🚚 Dashboard de Anomalías de Flete por Cliente")
st.markdown("**Análisis estadístico individualizado** — cada cliente se compara contra su propio patrón histórico")

# ============================================================
# ALERTA: ALCANCE DEL ANÁLISIS
# ============================================================
st.markdown("""
<div style="
    background: linear-gradient(135deg, #FEF3C7 0%, #FDE68A 100%);
    border-left: 6px solid #F59E0B;
    padding: 16px 20px;
    border-radius: 12px;
    margin: 16px 0;
    box-shadow: 0 2px 4px rgba(245, 158, 11, 0.1);
">
    <div style="font-size: 16px; font-weight: 600; color: #78350F; margin-bottom: 8px;">
        ⚠️ Alcance del análisis — Lee antes de interpretar
    </div>
    <div style="color: #78350F; line-height: 1.6;">
        Este dashboard analiza únicamente la columna <strong>"Flete"</strong> de la hoja 
        <em>Logística Nac</em>, que corresponde al <strong>costo base del transporte</strong> 
        cobrado por el proveedor de flete. Este análisis <strong>NO incluye</strong> los 
        costos adicionales que se suman al cargo final, tales como:
        <ul style="margin: 8px 0 4px 20px; padding: 0;">
            <li><strong>Custodia</strong> · seguridad/escolta del traslado</li>
            <li><strong>Estadías / Repartos</strong> · cargos por demora o reparto múltiple</li>
            <li><strong>Permisos</strong> · trámites o autorizaciones especiales</li>
            <li><strong>Rebate (NC)</strong> · descuentos vía notas de crédito</li>
            <li><strong>FEE Logístico</strong> · comisión administrativa</li>
            <li><strong>Flete Lukoil</strong> · cargos específicos de la marca</li>
        </ul>
        Estos conceptos forman parte del cálculo del <strong>Total Flete</strong>, pero 
        <strong>no se contemplan aquí</strong> porque introducirían ruido en la detección de 
        anomalías genuinas en la tarifa base. Si una operación tuvo cargos extras justificados 
        (ej. custodia por carga sensible), eso explicaría el aumento del Total Flete sin que 
        haya una anomalía real en la tarifa contratada.
    </div>
</div>
""", unsafe_allow_html=True)

# ============================================================
# KPIs PRINCIPALES
# ============================================================
col1, col2, col3, col4 = st.columns(4)

with col1:
    total_flete = df_filtrado['Flete'].sum()
    st.metric("💰 Total Flete", f"${total_flete:,.0f}")

with col2:
    n_clientes = df_filtrado['Nombre de Cliente'].nunique()
    st.metric("👥 Clientes analizados", f"{n_clientes}")

with col3:
    n_alto = (df_filtrado['Severidad'] == 'ALTO').sum()
    st.metric("🔴 Anomalías ALTO", f"{n_alto}")

with col4:
    n_medio = (df_filtrado['Severidad'] == 'MEDIO').sum()
    st.metric("🟡 Anomalías MEDIO", f"{n_medio}")

st.markdown("---")

# ============================================================
# TABLA PRINCIPAL DE ANOMALÍAS
# ============================================================
st.subheader("⚠️ Anomalías Detectadas")

solo_anomalias = st.checkbox("Mostrar solo anomalías (ALTO + MEDIO)", value=True)

if solo_anomalias:
    df_anomalias = df_filtrado[df_filtrado['Es Anomalía'] == 1].copy()
else:
    df_anomalias = df_filtrado.copy()

df_anomalias = df_anomalias.sort_values(
    by=['Severidad', 'Z_Flete'],
    key=lambda x: x.map({'ALTO': 0, 'MEDIO': 1, 'NORMAL': 2, 'INSUFICIENTE': 3}) if x.name == 'Severidad' else x.abs(),
    ascending=[True, False]
)

st.info(f"📌 Mostrando **{len(df_anomalias)}** registros · "
        f"🔴 ALTO: {(df_anomalias['Severidad'] == 'ALTO').sum()} · "
        f"🟡 MEDIO: {(df_anomalias['Severidad'] == 'MEDIO').sum()}")

# Columnas a mostrar
cols_tabla = [
    'Fecha Factura', 'Nombre de Cliente', 'Remisión', 'Folio NC',
    'Proveedor transporte',
    'Flete', 'Flete_media', 'Z_Flete',
    'Litros Fact', 'Litros_media', 'Z_Litros',
    'Costo por Litro', 'CxL_media', 'Z_CxL',
    'Severidad', 'Diagnóstico'
]
cols_existentes = [c for c in cols_tabla if c in df_anomalias.columns]

df_mostrar = df_anomalias[cols_existentes].copy()
if 'Fecha Factura' in df_mostrar.columns:
    df_mostrar['Fecha Factura'] = df_mostrar['Fecha Factura'].dt.strftime('%d/%m/%Y')


# Formato condicional
def colorear_severidad(val):
    if val == 'ALTO':
        return 'background-color: #FEE2E2; color: #991B1B; font-weight: bold;'
    elif val == 'MEDIO':
        return 'background-color: #FEF3C7; color: #92400E; font-weight: bold;'
    elif val == 'INSUFICIENTE':
        return 'background-color: #F3F4F6; color: #6B7280; font-style: italic;'
    return ''


def colorear_z(val):
    try:
        v = float(val)
        if abs(v) >= 2:
            return 'background-color: #FEE2E2; color: #991B1B; font-weight: bold;'
        elif abs(v) >= 1.5:
            return 'background-color: #FEF3C7; color: #92400E;'
        return ''
    except (ValueError, TypeError):
        return ''


format_dict = {
    'Flete': '${:,.2f}',
    'Flete_media': '${:,.0f}',
    'Litros Fact': '{:,.0f}',
    'Litros_media': '{:,.0f}',
    'Costo por Litro': '${:,.2f}',
    'CxL_media': '${:,.2f}',
    'Z_Flete': '{:+.2f}',
    'Z_Litros': '{:+.2f}',
    'Z_CxL': '{:+.2f}',
}
format_dict = {k: v for k, v in format_dict.items() if k in df_mostrar.columns}

styled = df_mostrar.style.format(format_dict)
if 'Severidad' in df_mostrar.columns:
    styled = styled.map(colorear_severidad, subset=['Severidad'])
for col in ['Z_Flete', 'Z_Litros', 'Z_CxL']:
    if col in df_mostrar.columns:
        styled = styled.map(colorear_z, subset=[col])

st.dataframe(styled, use_container_width=True, height=400)

# Botón de descarga
csv = df_mostrar.to_csv(index=False).encode('utf-8')
st.download_button(
    "📥 Descargar como CSV",
    csv,
    "anomalias_flete_por_cliente.csv",
    "text/csv"
)

# ============================================================
# DIAGNÓSTICOS DETALLADOS
# ============================================================
if len(df_anomalias[df_anomalias['Es Anomalía'] == 1]) > 0:
    st.markdown("---")
    st.subheader("🔍 Diagnósticos detallados")

    df_diag = df_anomalias[df_anomalias['Es Anomalía'] == 1].sort_values(
        by='Severidad',
        key=lambda x: x.map({'ALTO': 0, 'MEDIO': 1})
    ).head(10)

    for _, row in df_diag.iterrows():
        severity_class = 'severidad-alto' if row['Severidad'] == 'ALTO' else 'severidad-medio'
        st.markdown(
            f'<div class="{severity_class}">'
            f'<strong>{row["Nombre de Cliente"]}</strong> · '
            f'{row["Fecha Factura"].strftime("%d/%m/%Y") if pd.notna(row["Fecha Factura"]) else "N/A"} · '
            f'Remisión {row.get("Remisión", "N/A")}<br>'
            f'<small>{row["Diagnóstico"]}</small>'
            f'</div>',
            unsafe_allow_html=True
        )

# ============================================================
# GRÁFICO COMPARATIVO POR CLIENTE
# ============================================================
st.markdown("---")
st.subheader("📊 Comparativo por cliente — Flete vs su media histórica")

# Top clientes con anomalías
clientes_anomalias = df_filtrado[df_filtrado['Es Anomalía'] == 1].groupby('Nombre de Cliente').agg(
    Anomalias=('Es Anomalía', 'sum'),
    Flete_Total=('Flete', 'sum')
).reset_index().sort_values('Anomalias', ascending=False).head(15)

if len(clientes_anomalias) > 0:
    fig_clientes = go.Figure()

    fig_clientes.add_trace(go.Bar(
        y=clientes_anomalias['Nombre de Cliente'],
        x=clientes_anomalias['Anomalias'],
        orientation='h',
        marker_color='#DC2626',
        text=clientes_anomalias['Anomalias'],
        textposition='outside',
        hovertemplate='<b>%{y}</b><br>Anomalías: %{x}<br>Flete Total: $%{customdata:,.0f}<extra></extra>',
        customdata=clientes_anomalias['Flete_Total']
    ))

    fig_clientes.update_layout(
        height=max(300, len(clientes_anomalias) * 35),
        plot_bgcolor='white',
        paper_bgcolor='white',
        margin=dict(l=20, r=20, t=20, b=20),
        yaxis=dict(autorange='reversed'),
        xaxis=dict(title='Cantidad de anomalías')
    )
    st.plotly_chart(fig_clientes, use_container_width=True)
else:
    st.success("✅ No se detectaron anomalías con los filtros y umbrales actuales.")

# ============================================================
# GRÁFICO POR CLIENTE INDIVIDUAL
# ============================================================
st.markdown("---")
st.subheader("📈 Análisis individual por cliente")

# Seleccionar cliente para análisis detallado
clientes_con_anomalias = df_filtrado[df_filtrado['Es Anomalía'] == 1]['Nombre de Cliente'].unique().tolist()
clientes_disponibles = sorted(clientes_con_anomalias) if clientes_con_anomalias else clientes

if clientes_disponibles:
    cliente_detalle = st.selectbox(
        "Selecciona un cliente",
        options=clientes_disponibles,
        index=0,
        help="Visualiza el comportamiento histórico del cliente y sus anomalías"
    )

    df_cliente = df[df['Nombre de Cliente'] == cliente_detalle].sort_values('Fecha Factura')

    if len(df_cliente) > 0:
        # Stats del cliente
        col_a, col_b, col_c, col_d = st.columns(4)
        with col_a:
            st.metric("Registros", f"{len(df_cliente)}")
        with col_b:
            st.metric("Flete promedio", f"${df_cliente['Flete'].mean():,.0f}")
        with col_c:
            st.metric("CxL promedio", f"${df_cliente['Costo por Litro'].mean():.2f}")
        with col_d:
            st.metric("Anomalías", f"{int(df_cliente['Es Anomalía'].sum())}")

        # Gráfico con 3 paneles: Flete, Litros y CxL con bandas
        fig_indiv = make_subplots(
            rows=3, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.08,
            subplot_titles=('Flete pagado', 'Litros facturados', 'Costo por Litro (con bandas ±1σ y ±2σ)'),
            row_heights=[0.32, 0.32, 0.36]
        )

        # Marcadores según anomalía
        es_anom = df_cliente['Es Anomalía'] == 1
        colors_anom = ['#DC2626' if a else '#1E3A8A' for a in es_anom]
        sizes_anom = [12 if a else 6 for a in es_anom]

        # === PANEL 1: FLETE ===
        fig_indiv.add_trace(
            go.Scatter(
                x=df_cliente['Fecha Factura'],
                y=df_cliente['Flete'],
                mode='lines+markers',
                name='Flete',
                line=dict(color='#1E3A8A', width=2),
                marker=dict(size=sizes_anom, color=colors_anom),
                customdata=df_cliente[['Remisión', 'Folio NC', 'Proveedor transporte']].fillna('N/A').values,
                hovertemplate=(
                    '<b>%{x|%d/%m/%Y}</b><br>'
                    'Flete: $%{y:,.0f}<br>'
                    'Remisión: %{customdata[0]}<br>'
                    'Folio NC: %{customdata[1]}<br>'
                    'Proveedor: %{customdata[2]}'
                    '<extra></extra>'
                ),
                showlegend=False
            ),
            row=1, col=1
        )

        media_flete = df_cliente['Flete'].mean()
        fig_indiv.add_hline(
            y=media_flete, line_dash="dash", line_color="#888780",
            annotation_text=f"Media: ${media_flete:,.0f}",
            annotation_position="right",
            row=1, col=1
        )

        # === PANEL 2: LITROS ===
        fig_indiv.add_trace(
            go.Scatter(
                x=df_cliente['Fecha Factura'],
                y=df_cliente['Litros Fact'],
                mode='lines+markers',
                name='Litros',
                line=dict(color='#10B981', width=2),
                marker=dict(size=6, color='#10B981'),
                customdata=df_cliente[['Remisión', 'Folio NC', 'Proveedor transporte']].fillna('N/A').values,
                hovertemplate=(
                    '<b>%{x|%d/%m/%Y}</b><br>'
                    'Litros: %{y:,.0f}<br>'
                    'Remisión: %{customdata[0]}<br>'
                    'Folio NC: %{customdata[1]}<br>'
                    'Proveedor: %{customdata[2]}'
                    '<extra></extra>'
                ),
                showlegend=False
            ),
            row=2, col=1
        )

        media_litros = df_cliente['Litros Fact'].mean()
        fig_indiv.add_hline(
            y=media_litros, line_dash="dash", line_color="#888780",
            annotation_text=f"Media: {media_litros:,.0f}",
            annotation_position="right",
            row=2, col=1
        )

        # === PANEL 3: CxL CON BANDAS ESTADÍSTICAS ===
        media_cxl = df_cliente['Costo por Litro'].mean()
        std_cxl = df_cliente['Costo por Litro'].std()

        # Banda de ±2σ (zona crítica)
        banda_2sup = media_cxl + 2 * std_cxl
        banda_2inf = max(media_cxl - 2 * std_cxl, 0)

        # Banda de ±1σ (zona normal)
        banda_1sup = media_cxl + std_cxl
        banda_1inf = max(media_cxl - std_cxl, 0)

        # Líneas de fechas para las bandas
        fechas_cliente = df_cliente['Fecha Factura'].tolist()

        # Banda exterior +2σ (línea roja superior)
        fig_indiv.add_trace(
            go.Scatter(
                x=fechas_cliente,
                y=[banda_2sup] * len(fechas_cliente),
                mode='lines',
                line=dict(color='#DC2626', width=1, dash='dot'),
                name='+2σ',
                hovertemplate=f'+2σ: ${banda_2sup:.2f}<extra></extra>',
                showlegend=False
            ),
            row=3, col=1
        )

        # Banda exterior -2σ (línea roja inferior, con relleno hasta +2σ)
        fig_indiv.add_trace(
            go.Scatter(
                x=fechas_cliente,
                y=[banda_2inf] * len(fechas_cliente),
                mode='lines',
                line=dict(color='#DC2626', width=1, dash='dot'),
                fill='tonexty',
                fillcolor='rgba(220, 38, 38, 0.05)',
                name='-2σ',
                hovertemplate=f'-2σ: ${banda_2inf:.2f}<extra></extra>',
                showlegend=False
            ),
            row=3, col=1
        )

        # Banda interior +1σ (línea naranja)
        fig_indiv.add_trace(
            go.Scatter(
                x=fechas_cliente,
                y=[banda_1sup] * len(fechas_cliente),
                mode='lines',
                line=dict(color='#F59E0B', width=1, dash='dash'),
                name='+1σ',
                hovertemplate=f'+1σ: ${banda_1sup:.2f}<extra></extra>',
                showlegend=False
            ),
            row=3, col=1
        )

        # Banda interior -1σ (con relleno verde hasta +1σ = zona normal)
        fig_indiv.add_trace(
            go.Scatter(
                x=fechas_cliente,
                y=[banda_1inf] * len(fechas_cliente),
                mode='lines',
                line=dict(color='#F59E0B', width=1, dash='dash'),
                fill='tonexty',
                fillcolor='rgba(16, 185, 129, 0.08)',
                name='-1σ',
                hovertemplate=f'-1σ: ${banda_1inf:.2f}<extra></extra>',
                showlegend=False
            ),
            row=3, col=1
        )

        # Línea de media
        fig_indiv.add_hline(
            y=media_cxl, line_dash="dash", line_color="#475569",
            annotation_text=f"Media: ${media_cxl:.2f}",
            annotation_position="right",
            row=3, col=1
        )

        # Línea principal de Costo por Litro
        # Color según severidad: rojo si está fuera de ±2σ, amarillo si fuera de ±1σ
        cxl_values = df_cliente['Costo por Litro'].values
        colors_cxl = []
        sizes_cxl = []
        for cxl in cxl_values:
            if cxl > banda_2sup or cxl < banda_2inf:
                colors_cxl.append('#DC2626')  # Rojo - fuera de 2σ
                sizes_cxl.append(12)
            elif cxl > banda_1sup or cxl < banda_1inf:
                colors_cxl.append('#F59E0B')  # Amarillo - fuera de 1σ
                sizes_cxl.append(8)
            else:
                colors_cxl.append('#1E3A8A')  # Azul - dentro de 1σ
                sizes_cxl.append(6)

        fig_indiv.add_trace(
            go.Scatter(
                x=df_cliente['Fecha Factura'],
                y=df_cliente['Costo por Litro'],
                mode='lines+markers',
                name='Costo/L',
                line=dict(color='#1E3A8A', width=2.5),
                marker=dict(size=sizes_cxl, color=colors_cxl, line=dict(color=colors_cxl, width=1)),
                customdata=df_cliente[['Remisión', 'Folio NC', 'Flete', 'Litros Fact', 'Proveedor transporte']].fillna(
                    'N/A').values,
                hovertemplate=(
                    '<b>%{x|%d/%m/%Y}</b><br>'
                    '$/L: $%{y:.2f}<br>'
                    'Remisión: %{customdata[0]}<br>'
                    'Folio NC: %{customdata[1]}<br>'
                    'Flete: $%{customdata[2]:,.0f}<br>'
                    'Litros: %{customdata[3]:,.0f}<br>'
                    'Proveedor: %{customdata[4]}'
                    '<extra></extra>'
                ),
                showlegend=False
            ),
            row=3, col=1
        )

        # Configuración general
        fig_indiv.update_layout(
            height=700,
            showlegend=False,
            plot_bgcolor='white',
            paper_bgcolor='white',
            margin=dict(l=20, r=80, t=40, b=20),
            hovermode='x unified'
        )
        fig_indiv.update_xaxes(showgrid=False)
        fig_indiv.update_yaxes(showgrid=True, gridcolor='#F1F5F9')
        fig_indiv.update_yaxes(title_text='$', row=1, col=1)
        fig_indiv.update_yaxes(title_text='L', row=2, col=1)
        fig_indiv.update_yaxes(title_text='$/L', row=3, col=1)

        st.plotly_chart(fig_indiv, use_container_width=True)

        # Leyenda visual de zonas
        col_leg1, col_leg2, col_leg3 = st.columns(3)
        with col_leg1:
            st.markdown(
                '<div style="background:rgba(16,185,129,0.15);padding:8px 12px;'
                'border-radius:8px;border-left:4px solid #10B981;font-size:13px;">'
                '🟢 <strong>Zona normal</strong> (±1σ): comportamiento esperado</div>',
                unsafe_allow_html=True
            )
        with col_leg2:
            st.markdown(
                '<div style="background:rgba(245,158,11,0.15);padding:8px 12px;'
                'border-radius:8px;border-left:4px solid #F59E0B;font-size:13px;">'
                '🟡 <strong>Zona de alerta</strong> (1σ–2σ): elevado pero no crítico</div>',
                unsafe_allow_html=True
            )
        with col_leg3:
            st.markdown(
                '<div style="background:rgba(220,38,38,0.15);padding:8px 12px;'
                'border-radius:8px;border-left:4px solid #DC2626;font-size:13px;">'
                '🔴 <strong>Zona crítica</strong> (>2σ): anomalía estadística</div>',
                unsafe_allow_html=True
            )

        # Resumen del cliente
        st.markdown(f"""
        **Resumen del cliente {cliente_detalle}:**
        - Total de operaciones: {len(df_cliente)}
        - Flete promedio: ${df_cliente['Flete'].mean():,.0f} (σ = ${df_cliente['Flete'].std():,.0f})
        - Litros promedio: {df_cliente['Litros Fact'].mean():,.0f} (σ = {df_cliente['Litros Fact'].std():,.0f})
        - Costo por litro promedio: ${df_cliente['Costo por Litro'].mean():.2f} (σ = ${df_cliente['Costo por Litro'].std():.2f})
        """)

# ============================================================
# FOOTER
# ============================================================
st.markdown("---")
st.caption(
    f"💡 **Modelo:** Z-scores POR CLIENTE · "
    f"Umbrales: ALTO ≥ {umbral_alto}σ, MEDIO ≥ {umbral_medio}σ · "
    f"Mínimo {min_registros} registros por cliente · "
    f"Total registros analizados: {len(df_filtrado):,}"
)