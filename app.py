"""
Dashboard de Auditoría Logística — v7
======================================
Dashboard con DOS pestañas:

  📈 PESTAÑA 1 — Anomalías de Flete por Cliente
     Detección estadística de saltos atípicos en el costo de flete
     usando Z-scores comparados contra el patrón histórico del cliente.

  🔎 PESTAÑA 2 — Facturas sin Match en SAP
     Auditoría que cruza las facturas de transporte de Logística Nac
     contra SAP proveedores, detectando errores de captura tipográficos,
     UUIDs inválidos y posibles duplicados.

INSTALACIÓN:
    pip install streamlit pandas numpy plotly openpyxl python-Levenshtein

EJECUCIÓN:
    streamlit run app.py
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import re

# ============================================================
# CONFIGURACIÓN DE LA PÁGINA
# ============================================================
st.set_page_config(
    page_title="Auditoría Logística",
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

    /* Estilos para tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        height: 50px;
        background: #F1F5F9;
        border-radius: 10px 10px 0 0;
        padding: 12px 20px;
        font-weight: 600;
    }
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, #1E3A8A 0%, #1E40AF 100%) !important;
        color: white !important;
    }
</style>
""", unsafe_allow_html=True)


# ============================================================
# UTILIDADES COMPARTIDAS
# ============================================================
@st.cache_data
def cargar_logistica(ruta_archivo):
    """Carga la hoja 'Logistica Nac' (encabezados en fila 4)."""
    df = pd.read_excel(ruta_archivo, sheet_name="Logistica Nac", header=3)
    df.columns = [str(c).strip() for c in df.columns]
    if 'Fecha Factura' in df.columns:
        df['Fecha Factura'] = pd.to_datetime(df['Fecha Factura'], errors='coerce')
    cols_numericas = ['Flete', 'Litros Fact', 'Litros Rem', 'Total Flete', 'CXL']
    for col in cols_numericas:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    return df


@st.cache_data
def cargar_sap(ruta_archivo):
    """Carga la hoja 'SAP proveedores'."""
    df = pd.read_excel(ruta_archivo, sheet_name="SAP proveedores")
    df.columns = [str(c).strip() for c in df.columns]
    return df


# ============================================================
# DETECCIÓN DE ANOMALÍAS POR CLIENTE
# ============================================================
def detectar_anomalias_por_cliente(df, umbral_z_alto=2.0, umbral_z_medio=1.5, min_registros=3):
    """Detecta anomalías comparando contra la media histórica del MISMO CLIENTE."""
    df = df.copy()
    df = df.dropna(subset=['Fecha Factura', 'Nombre de Cliente'])
    df = df[df['Flete'].notna() & (df['Flete'] > 0)]
    df = df[df['Litros Fact'].notna() & (df['Litros Fact'] > 0)]
    df['Costo por Litro'] = df['Flete'] / df['Litros Fact']

    stats_cliente = df.groupby('Nombre de Cliente').agg(
        Flete_media=('Flete', 'mean'),
        Flete_std=('Flete', 'std'),
        Litros_media=('Litros Fact', 'mean'),
        Litros_std=('Litros Fact', 'std'),
        CxL_media=('Costo por Litro', 'mean'),
        CxL_std=('Costo por Litro', 'std'),
        Num_registros=('Flete', 'count')
    ).reset_index()

    df = df.merge(stats_cliente, on='Nombre de Cliente', how='left')

    df['Z_Flete'] = np.where(df['Flete_std'] > 0,
                             (df['Flete'] - df['Flete_media']) / df['Flete_std'], 0)
    df['Z_Litros'] = np.where(df['Litros_std'] > 0,
                              (df['Litros Fact'] - df['Litros_media']) / df['Litros_std'], 0)
    df['Z_CxL'] = np.where(df['CxL_std'] > 0,
                           (df['Costo por Litro'] - df['CxL_media']) / df['CxL_std'], 0)

    def clasificar(row):
        if row['Num_registros'] < min_registros:
            return 'INSUFICIENTE'
        z_flete = row['Z_Flete']
        z_litros = row['Z_Litros']
        z_cxl = row['Z_CxL']
        if z_cxl < umbral_z_medio:
            return 'NORMAL'
        if z_cxl >= umbral_z_alto and (z_flete >= umbral_z_alto or z_litros < 0.5):
            return 'ALTO'
        if z_cxl >= umbral_z_medio:
            return 'MEDIO'
        return 'NORMAL'

    df['Severidad'] = df.apply(clasificar, axis=1)
    df['Es Anomalía'] = df['Severidad'].isin(['ALTO', 'MEDIO']).astype(int)

    def diagnostico(row):
        if row['Severidad'] == 'NORMAL':
            return ''
        if row['Severidad'] == 'INSUFICIENTE':
            return f'⚪ Cliente con pocos registros ({int(row["Num_registros"])}) - no evaluable'
        z_flete, z_litros, z_cxl = row['Z_Flete'], row['Z_Litros'], row['Z_CxL']
        sf = '+' if z_flete > 0 else ''
        sl = '+' if z_litros > 0 else ''
        sc = '+' if z_cxl > 0 else ''
        if row['Severidad'] == 'ALTO':
            if abs(z_litros) < 1:
                return (f'🔴 FLETE atípico ({sf}{z_flete:.1f}σ vs media cliente '
                        f'${row["Flete_media"]:,.0f}) SIN salto proporcional en LITROS '
                        f'({sl}{z_litros:.1f}σ). CxL ${row["Costo por Litro"]:.2f} '
                        f'vs media ${row["CxL_media"]:.2f} ({sc}{z_cxl:.1f}σ). '
                        f'Probable error o cargo no justificado — REVISAR.')
            return (f'🔴 FLETE atípico ({sf}{z_flete:.1f}σ) y CxL elevado '
                    f'({sc}{z_cxl:.1f}σ vs media cliente). REVISAR.')
        return (f'🟡 FLETE alto ({sf}{z_flete:.1f}σ) y litros '
                f'{"también altos" if abs(z_litros) > 0.5 else "normales"} '
                f'({sl}{z_litros:.1f}σ); CxL elevado ({sc}{z_cxl:.1f}σ). Verificar.')

    df['Diagnóstico'] = df.apply(diagnostico, axis=1)
    return df


# ============================================================
# AUDITORÍA: FACTURAS SIN MATCH EN SAP
# ============================================================
UUID_REGEX = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')


def es_uuid(texto):
    """Verifica si una cadena tiene formato UUID válido."""
    if not isinstance(texto, str):
        return False
    return bool(UUID_REGEX.match(texto.strip()))


def parece_uuid(texto):
    """UUID 'casi válido' (~36 chars con guiones) — útil para typos."""
    if not isinstance(texto, str):
        return False
    t = texto.strip()
    if len(t) < 30 or len(t) > 42:
        return False
    return t.count('-') >= 3


def levenshtein(s1, s2):
    """Distancia de Levenshtein entre dos cadenas (implementación pura)."""
    if not isinstance(s1, str) or not isinstance(s2, str):
        return 999
    s1, s2 = s1.upper().strip(), s2.upper().strip()
    if len(s1) < len(s2):
        s1, s2 = s2, s1
    if len(s2) == 0:
        return len(s1)
    previous = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        current = [i + 1]
        for j, c2 in enumerate(s2):
            insert_cost = previous[j + 1] + 1
            delete_cost = current[j] + 1
            replace_cost = previous[j] + (c1 != c2)
            current.append(min(insert_cost, delete_cost, replace_cost))
        previous = current
    return previous[-1]


def explicar_typo(texto_logistica, texto_sap):
    """Genera explicación humana del tipo de error tipográfico."""
    a = str(texto_logistica).upper().strip()
    b = str(texto_sap).upper().strip()
    if a == b:
        return "coincidencia exacta"
    if len(a) != len(b):
        diff = abs(len(a) - len(b))
        if diff == 1:
            return f"falta o sobra 1 carácter"
        return f"diferencia de {diff} caracteres en longitud"
    # Misma longitud — buscar diferencias
    diferencias = []
    for i, (ca, cb) in enumerate(zip(a, b)):
        if ca != cb:
            diferencias.append((i, ca, cb))
    if len(diferencias) == 1:
        i, ca, cb = diferencias[0]
        return f"un carácter cambiado en posición {i + 1}: '{ca}' debería ser '{cb}'"
    if len(diferencias) == 2:
        # Verificar si son caracteres intercambiados
        d1, d2 = diferencias
        if d1[1] == d2[2] and d1[2] == d2[1] and d2[0] - d1[0] <= 2:
            return f"caracteres intercambiados ('{d1[1]}' y '{d2[1]}' aparecen invertidos)"
        return f"2 caracteres distintos"
    return f"{len(diferencias)} caracteres distintos"


def split_facturas(texto):
    """Divide una celda con varias facturas separadas por /, , o ;."""
    if pd.isna(texto):
        return []
    return [t.strip() for t in re.split(r'[/,;]', str(texto)) if t.strip()]


def auditar_facturas(df_log, df_sap, tolerancia_monto=1.0):
    """
    Cruza Logística Nac contra SAP proveedores y clasifica cada factura.

    Categorías:
    - PROVISION (provisión contable, no requiere match)
    - COINCIDE_EXACTO (match en SAP, sin issues)
    - UUID_TYPO_CON_MONTO_COINCIDENTE / UUID_POSIBLE_TYPO_SIN_MONTO
    - UUID_MONTO_COINCIDE_DISTINTO / UUID_NO_ENCONTRADO / UUID_FORMATO_INVALIDO
    - TYPO_CON_MONTO_COINCIDENTE / POSIBLE_TYPO_SIN_MONTO
    - MONTO_COINCIDE_REF_DISTINTA / NO_ENCONTRADO
    """
    # Preparar SAP: referencias, UUIDs y montos
    sap_refs = df_sap['Referencia Factura'].dropna().astype(str).str.strip().tolist()
    sap_uuids = df_sap['UUID Factura'].dropna().astype(str).str.strip().tolist()

    # Map: ref/uuid -> (índice fila SAP, total sin IVA, total movimiento)
    ref_to_data = {}
    for idx, row in df_sap.iterrows():
        ref = row.get('Referencia Factura')
        if pd.notna(ref):
            ref_to_data[str(ref).strip().upper()] = {
                'fila_sap': idx + 2,  # +2 por el header de Excel (no 0-index)
                'total_sin_iva': row.get('Total Sin IVA'),
                'total_mov': row.get('Total Movimiento'),
                'ref_original': str(ref).strip()
            }

    uuid_to_data = {}
    for idx, row in df_sap.iterrows():
        u = row.get('UUID Factura')
        if pd.notna(u):
            uuid_to_data[str(u).strip().upper()] = {
                'fila_sap': idx + 2,
                'total_sin_iva': row.get('Total Sin IVA'),
                'total_mov': row.get('Total Movimiento'),
                'uuid_original': str(u).strip()
            }

    resultados = []

    for idx, row in df_log.iterrows():
        fac_transp = row.get('Factura transporte')
        proveedor = row.get('Proveedor transporte')
        total_flete = row.get('Total Flete') if 'Total Flete' in row.index else row.get('Total Flete ')

        # Filtros: ignorar filas vacías o proveedor = CLIENTE
        if pd.isna(fac_transp):
            continue
        if pd.notna(proveedor) and str(proveedor).strip().upper() == 'CLIENTE':
            continue

        # Una celda puede traer varias facturas separadas
        facturas = split_facturas(fac_transp)
        if not facturas:
            continue

        for factura in facturas:
            f_upper = factura.upper().strip()

            # PROVISION
            if 'PROVISION' in f_upper or 'PROVISON' in f_upper:
                resultados.append({
                    'idx_log': idx,
                    'factura_evaluada': factura,
                    'Categoría': 'PROVISION',
                    'Razón': 'Marca de provisión contable — no requiere match en SAP.',
                })
                continue

            # ¿Es UUID?
            es_uuid_valido = es_uuid(factura)
            parece_uuid_aprox = parece_uuid(factura) and not es_uuid_valido

            if es_uuid_valido or parece_uuid_aprox:
                # ===== CASO UUID =====
                if not es_uuid_valido:
                    # Formato no estándar
                    resultados.append({
                        'idx_log': idx,
                        'factura_evaluada': factura,
                        'Categoría': 'UUID_FORMATO_INVALIDO',
                        'Razón': f'El identificador "{factura}" parece UUID pero su formato es inválido (debe ser 8-4-4-4-12 caracteres hexadecimales).',
                    })
                    continue

                # Match exacto en UUIDs SAP
                if f_upper in uuid_to_data:
                    data = uuid_to_data[f_upper]
                    resultados.append({
                        'idx_log': idx,
                        'factura_evaluada': factura,
                        'Categoría': 'COINCIDE_EXACTO',
                        'Razón': f'UUID encontrado en SAP (fila {data["fila_sap"]}, monto ${data["total_sin_iva"]:,.2f}).',
                    })
                    continue

                # Buscar UUIDs similares (Levenshtein <= 3)
                candidatos = []
                for u_sap, data in uuid_to_data.items():
                    d = levenshtein(f_upper, u_sap)
                    if d <= 3 and d > 0:
                        candidatos.append((d, u_sap, data))
                candidatos.sort()

                if candidatos:
                    # ¿Algún candidato tiene monto coincidente?
                    match_monto = None
                    for d, u_sap, data in candidatos:
                        for col_monto in ['total_sin_iva', 'total_mov']:
                            if pd.notna(data[col_monto]) and pd.notna(total_flete):
                                if abs(float(data[col_monto]) - float(total_flete)) <= tolerancia_monto:
                                    match_monto = (d, u_sap, data, col_monto)
                                    break
                        if match_monto:
                            break

                    if match_monto:
                        d, u_sap, data, col = match_monto
                        explicacion = explicar_typo(factura, data['uuid_original'])
                        resultados.append({
                            'idx_log': idx,
                            'factura_evaluada': factura,
                            'Categoría': 'UUID_TYPO_CON_MONTO_COINCIDENTE',
                            'Razón': (f'POSIBLE ERROR DE CAPTURA en UUID: "{factura}" en Logística vs '
                                      f'"{data["uuid_original"]}" en SAP (fila {data["fila_sap"]}). '
                                      f'Monto coincide (${total_flete:,.2f}). Diferencia: {explicacion}. '
                                      f'Alta confianza de error tipográfico al copiar/pegar.'),
                        })
                    else:
                        candidatos_str = '; '.join([
                            f'"{c[1]}" (fila {c[2]["fila_sap"]}, ${c[2]["total_sin_iva"]:,.2f})'
                            for c in candidatos[:3]
                        ])
                        resultados.append({
                            'idx_log': idx,
                            'factura_evaluada': factura,
                            'Categoría': 'UUID_POSIBLE_TYPO_SIN_MONTO',
                            'Razón': (f'UUID "{factura}" no encontrado. Candidatos similares: {candidatos_str}. '
                                      f'Verificar manualmente.'),
                        })
                    continue

                # Sin similares — ¿algún UUID con monto exacto?
                if pd.notna(total_flete):
                    for u_sap, data in uuid_to_data.items():
                        for col_monto in ['total_sin_iva', 'total_mov']:
                            if pd.notna(data[col_monto]):
                                if abs(float(data[col_monto]) - float(total_flete)) <= tolerancia_monto:
                                    resultados.append({
                                        'idx_log': idx,
                                        'factura_evaluada': factura,
                                        'Categoría': 'UUID_MONTO_COINCIDE_DISTINTO',
                                        'Razón': (f'UUID "{factura}" no encontrado, pero hay un UUID en SAP con '
                                                  f'monto exacto ${total_flete:,.2f}: "{data["uuid_original"]}" '
                                                  f'(fila {data["fila_sap"]}). Posible factura registrada con UUID diferente.'),
                                    })
                                    break
                        else:
                            continue
                        break
                    else:
                        resultados.append({
                            'idx_log': idx,
                            'factura_evaluada': factura,
                            'Categoría': 'UUID_NO_ENCONTRADO',
                            'Razón': f'UUID "{factura}" no existe en SAP y no hay coincidencias por monto.',
                        })
                else:
                    resultados.append({
                        'idx_log': idx,
                        'factura_evaluada': factura,
                        'Categoría': 'UUID_NO_ENCONTRADO',
                        'Razón': f'UUID "{factura}" no existe en SAP.',
                    })

            else:
                # ===== CASO REFERENCIA (texto/clave/número) =====
                # Match exacto en referencias
                if f_upper in ref_to_data:
                    data = ref_to_data[f_upper]
                    resultados.append({
                        'idx_log': idx,
                        'factura_evaluada': factura,
                        'Categoría': 'COINCIDE_EXACTO',
                        'Razón': f'Referencia encontrada en SAP (fila {data["fila_sap"]}, monto ${data["total_sin_iva"]:,.2f}).',
                    })
                    continue

                # Buscar similares (Levenshtein <= 2)
                candidatos = []
                for r_sap, data in ref_to_data.items():
                    d = levenshtein(f_upper, r_sap)
                    if 0 < d <= 2:
                        candidatos.append((d, r_sap, data))
                candidatos.sort()

                if candidatos:
                    # ¿Monto coincidente?
                    match_monto = None
                    for d, r_sap, data in candidatos:
                        for col_monto in ['total_sin_iva', 'total_mov']:
                            if pd.notna(data[col_monto]) and pd.notna(total_flete):
                                if abs(float(data[col_monto]) - float(total_flete)) <= tolerancia_monto:
                                    match_monto = (d, r_sap, data, col_monto)
                                    break
                        if match_monto:
                            break

                    if match_monto:
                        d, r_sap, data, col = match_monto
                        explicacion = explicar_typo(factura, data['ref_original'])
                        resultados.append({
                            'idx_log': idx,
                            'factura_evaluada': factura,
                            'Categoría': 'TYPO_CON_MONTO_COINCIDENTE',
                            'Razón': (f'POSIBLE ERROR DE CAPTURA en referencia: "{factura}" en Logística vs '
                                      f'"{data["ref_original"]}" en SAP (fila {data["fila_sap"]}). '
                                      f'Monto coincide (${total_flete:,.2f}). Diferencia: {explicacion}. '
                                      f'Probable error tipográfico — se sugiere corregir en Logística.'),
                        })
                    else:
                        candidatos_str = '; '.join([
                            f'"{c[2]["ref_original"]}" (fila {c[2]["fila_sap"]}, ${c[2]["total_sin_iva"]:,.2f})'
                            for c in candidatos[:3]
                        ])
                        resultados.append({
                            'idx_log': idx,
                            'factura_evaluada': factura,
                            'Categoría': 'POSIBLE_TYPO_SIN_MONTO',
                            'Razón': (f'Referencia "{factura}" no encontrada. Candidatos similares: {candidatos_str}. '
                                      f'Verificar manualmente.'),
                        })
                    continue

                # Sin similares — ¿monto exacto en otra ref?
                if pd.notna(total_flete):
                    encontrado = False
                    for r_sap, data in ref_to_data.items():
                        for col_monto in ['total_sin_iva', 'total_mov']:
                            if pd.notna(data[col_monto]):
                                if abs(float(data[col_monto]) - float(total_flete)) <= tolerancia_monto:
                                    resultados.append({
                                        'idx_log': idx,
                                        'factura_evaluada': factura,
                                        'Categoría': 'MONTO_COINCIDE_REF_DISTINTA',
                                        'Razón': (f'Referencia "{factura}" no encontrada, pero hay una factura en SAP '
                                                  f'con monto exacto ${total_flete:,.2f}: "{data["ref_original"]}" '
                                                  f'(fila {data["fila_sap"]}). Posible factura registrada con clave diferente.'),
                                    })
                                    encontrado = True
                                    break
                        if encontrado:
                            break
                    if not encontrado:
                        resultados.append({
                            'idx_log': idx,
                            'factura_evaluada': factura,
                            'Categoría': 'NO_ENCONTRADO',
                            'Razón': f'Referencia "{factura}" no existe en SAP y no hay coincidencias por monto.',
                        })
                else:
                    resultados.append({
                        'idx_log': idx,
                        'factura_evaluada': factura,
                        'Categoría': 'NO_ENCONTRADO',
                        'Razón': f'Referencia "{factura}" no existe en SAP.',
                    })

    # Construir DataFrame de resultados con todas las columnas de Logística + categoría/razón
    if not resultados:
        return pd.DataFrame()

    df_res = pd.DataFrame(resultados)
    df_log_full = df_log.reset_index(drop=False).rename(columns={'index': 'idx_log_orig'})
    df_log_full['idx_log_orig'] = df_log_full.index  # asegurar que los idx coincidan

    # Reset index del df_log original para hacer merge
    df_log_indexed = df_log.reset_index(drop=True)
    df_log_indexed['idx_log'] = df_log_indexed.index

    df_final = df_res.merge(df_log_indexed, on='idx_log', how='left')

    # Renombrar para humano
    if 'Categoría' in df_final.columns and 'Razón' in df_final.columns:
        df_final = df_final.rename(columns={'Razón': 'Razón de No Coincidencia'})

    return df_final


# ============================================================
# DICCIONARIO DE CATEGORÍAS — Etiquetas humanas y colores
# ============================================================
CATEGORIAS_INFO = {
    'COINCIDE_EXACTO': {
        'label': '✅ Coincide exactamente',
        'color': '#16A34A',
        'bg': '#DCFCE7',
        'desc': 'La factura existe en SAP con coincidencia exacta. Sin observaciones.',
    },
    'PROVISION': {
        'label': '📋 Provisión contable',
        'color': '#3B82F6',
        'bg': '#DBEAFE',
        'desc': 'Asiento de provisión contable — no requiere match con factura física.',
    },
    'TYPO_CON_MONTO_COINCIDENTE': {
        'label': '🟢 Error de captura confirmado (monto coincide)',
        'color': '#15803D',
        'bg': '#BBF7D0',
        'desc': 'La referencia en Logística difiere de SAP por un error de captura, pero el monto coincide exactamente. Alta confianza de que es un error tipográfico al transcribir.',
    },
    'UUID_TYPO_CON_MONTO_COINCIDENTE': {
        'label': '🟢 Error de captura en UUID (monto coincide)',
        'color': '#15803D',
        'bg': '#BBF7D0',
        'desc': 'El UUID en Logística difiere ligeramente del de SAP, pero el monto coincide. Probable error al copiar/pegar el UUID.',
    },
    'POSIBLE_TYPO_SIN_MONTO': {
        'label': '🟠 Posible error de captura (monto NO verificable)',
        'color': '#C2410C',
        'bg': '#FED7AA',
        'desc': 'Hay referencias parecidas en SAP pero el monto no coincide o no se pudo verificar. Requiere revisión manual.',
    },
    'UUID_POSIBLE_TYPO_SIN_MONTO': {
        'label': '🟠 Posible error de captura en UUID',
        'color': '#C2410C',
        'bg': '#FED7AA',
        'desc': 'Hay UUIDs parecidos en SAP pero el monto no coincide. Requiere revisión manual.',
    },
    'MONTO_COINCIDE_REF_DISTINTA': {
        'label': '🟡 Monto coincide pero referencia distinta',
        'color': '#A16207',
        'bg': '#FEF08A',
        'desc': 'La referencia no existe en SAP, pero hay una factura con el mismo monto registrada con una clave totalmente diferente.',
    },
    'UUID_MONTO_COINCIDE_DISTINTO': {
        'label': '🟡 Monto coincide pero UUID distinto',
        'color': '#A16207',
        'bg': '#FEF08A',
        'desc': 'El UUID no existe en SAP, pero hay una factura con el mismo monto bajo otro UUID.',
    },
    'NO_ENCONTRADO': {
        'label': '🔴 No encontrado en SAP',
        'color': '#B91C1C',
        'bg': '#FECACA',
        'desc': 'La referencia no existe en SAP y no hay coincidencias por monto. Posible factura faltante de registrar.',
    },
    'UUID_NO_ENCONTRADO': {
        'label': '🔴 UUID no encontrado en SAP',
        'color': '#B91C1C',
        'bg': '#FECACA',
        'desc': 'El UUID no existe en SAP y no hay coincidencias por monto.',
    },
    'UUID_FORMATO_INVALIDO': {
        'label': '⚪ UUID con formato inválido',
        'color': '#525252',
        'bg': '#E5E5E5',
        'desc': 'El identificador parece UUID pero no cumple el formato 8-4-4-4-12 hexadecimal.',
    },
}

# ============================================================
# SIDEBAR — CARGA DE ARCHIVO
# ============================================================
st.sidebar.title("⚙️ Configuración")

archivo = st.sidebar.file_uploader(
    "📁 Sube tu archivo Excel",
    type=['xlsx', 'xls'],
    help="Excel con hojas 'Logistica Nac' y 'SAP proveedores'"
)

if archivo is None:
    st.title("🚚 Dashboard de Auditoría Logística")
    st.warning("Por favor, sube el archivo Excel desde la barra lateral para visualizar el dashboard.")

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("""
        ### 📈 Pestaña 1 — Anomalías de Flete
        Detecta saltos atípicos en el costo del transporte comparando 
        cada operación contra el patrón histórico **del mismo cliente**.

        - Análisis estadístico con Z-scores
        - Tres niveles de severidad
        - Visualización con bandas estadísticas
        """)
    with col_b:
        st.markdown("""
        ### 🔎 Pestaña 2 — Facturas vs SAP
        Cruza las facturas de transporte de Logística contra SAP 
        proveedores y detecta discrepancias.

        - Detección de errores de captura
        - Búsqueda por monto cuando falla la referencia
        - Diagnóstico humano en cada caso
        """)
    st.stop()

# Cargar ambas hojas
try:
    df_log_raw = cargar_logistica(archivo)
except Exception as e:
    st.error(f"Error al cargar 'Logistica Nac': {e}")
    st.stop()

try:
    df_sap = cargar_sap(archivo)
except Exception as e:
    st.error(f"Error al cargar 'SAP proveedores': {e}")
    st.stop()

# ============================================================
# HEADER
# ============================================================
st.title("🚚 Dashboard de Auditoría Logística")
st.markdown("Sistema integrado de detección de anomalías y conciliación de facturas")

# ============================================================
# TABS
# ============================================================
tab1, tab2 = st.tabs([
    "📈  Anomalías de Flete por Cliente",
    "🔎  Facturas sin Match en SAP"
])

# ╔══════════════════════════════════════════════════════════╗
# ║  PESTAÑA 1 — ANOMALÍAS DE FLETE                          ║
# ╚══════════════════════════════════════════════════════════╝
with tab1:
    st.markdown("**Análisis estadístico individualizado** — cada cliente se compara contra su propio patrón histórico")

    # Alerta de alcance
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
            Este análisis usa únicamente la columna <strong>"Flete"</strong> de la hoja 
            <em>Logística Nac</em>, que corresponde al <strong>costo base del transporte</strong>. 
            <strong>NO incluye</strong> cargos adicionales como Custodia, Estadías/Repartos, 
            Permisos, Rebate (NC), FEE Logístico ni Flete Lukoil. Estos forman parte del 
            <strong>Total Flete</strong> pero se omiten aquí para no introducir ruido en la 
            detección de anomalías de tarifa base.
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Parámetros sidebar (solo aplicables a tab1)
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 📈 Pestaña: Anomalías de Flete")
    umbral_alto = st.sidebar.slider("Umbral ALTO (σ)", 1.5, 3.5, 2.0, 0.1)
    umbral_medio = st.sidebar.slider("Umbral MEDIO (σ)", 1.0, 2.5, 1.5, 0.1)
    min_registros = st.sidebar.slider("Mínimo registros por cliente", 2, 10, 3)

    df = detectar_anomalias_por_cliente(df_log_raw, umbral_alto, umbral_medio, min_registros)

    # Filtros
    st.sidebar.markdown("**Filtros (Pestaña 1)**")
    clientes = sorted(df['Nombre de Cliente'].dropna().unique())
    cliente_sel = st.sidebar.multiselect("Cliente", options=clientes, default=[], key="cli_t1")

    fecha_min = df['Fecha Factura'].min().date()
    fecha_max = df['Fecha Factura'].max().date()
    rango_fechas = st.sidebar.date_input(
        "Rango de fechas", value=(fecha_min, fecha_max),
        min_value=fecha_min, max_value=fecha_max, key="fec_t1"
    )

    severidad_sel = st.sidebar.multiselect(
        "Severidad",
        options=['ALTO', 'MEDIO', 'NORMAL', 'INSUFICIENTE'],
        default=[], key="sev_t1"
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

    # KPIs
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("💰 Total Flete", f"${df_filtrado['Flete'].sum():,.0f}")
    with col2:
        st.metric("👥 Clientes analizados", f"{df_filtrado['Nombre de Cliente'].nunique()}")
    with col3:
        st.metric("🔴 Anomalías ALTO", f"{(df_filtrado['Severidad'] == 'ALTO').sum()}")
    with col4:
        st.metric("🟡 Anomalías MEDIO", f"{(df_filtrado['Severidad'] == 'MEDIO').sum()}")

    st.markdown("---")
    st.subheader("⚠️ Anomalías Detectadas")
    solo_anomalias = st.checkbox("Mostrar solo anomalías (ALTO + MEDIO)", value=True, key="solo_anom_t1")

    df_anom = df_filtrado[df_filtrado['Es Anomalía'] == 1].copy() if solo_anomalias else df_filtrado.copy()
    df_anom = df_anom.sort_values(
        by=['Severidad', 'Z_Flete'],
        key=lambda x: x.map(
            {'ALTO': 0, 'MEDIO': 1, 'NORMAL': 2, 'INSUFICIENTE': 3}) if x.name == 'Severidad' else x.abs(),
        ascending=[True, False]
    )

    st.info(f"📌 Mostrando **{len(df_anom)}** registros · "
            f"🔴 ALTO: {(df_anom['Severidad'] == 'ALTO').sum()} · "
            f"🟡 MEDIO: {(df_anom['Severidad'] == 'MEDIO').sum()}")

    cols_tabla = [
        'Fecha Factura', 'Nombre de Cliente', 'Remisión', 'Folio NC',
        'Proveedor transporte',
        'Flete', 'Flete_media', 'Z_Flete',
        'Litros Fact', 'Litros_media', 'Z_Litros',
        'Costo por Litro', 'CxL_media', 'Z_CxL',
        'Severidad', 'Diagnóstico'
    ]
    cols_existentes = [c for c in cols_tabla if c in df_anom.columns]
    df_show = df_anom[cols_existentes].copy()
    if 'Fecha Factura' in df_show.columns:
        df_show['Fecha Factura'] = df_show['Fecha Factura'].dt.strftime('%d/%m/%Y')


    def colorear_severidad(val):
        if val == 'ALTO':
            return 'background-color: #FEE2E2; color: #991B1B; font-weight: bold;'
        if val == 'MEDIO':
            return 'background-color: #FEF3C7; color: #92400E; font-weight: bold;'
        if val == 'INSUFICIENTE':
            return 'background-color: #F3F4F6; color: #6B7280; font-style: italic;'
        return ''


    def colorear_z(val):
        try:
            v = float(val)
            if abs(v) >= 2:
                return 'background-color: #FEE2E2; color: #991B1B; font-weight: bold;'
            if abs(v) >= 1.5:
                return 'background-color: #FEF3C7; color: #92400E;'
        except (ValueError, TypeError):
            pass
        return ''


    fmt = {
        'Flete': '${:,.2f}', 'Flete_media': '${:,.0f}',
        'Litros Fact': '{:,.0f}', 'Litros_media': '{:,.0f}',
        'Costo por Litro': '${:,.2f}', 'CxL_media': '${:,.2f}',
        'Z_Flete': '{:+.2f}', 'Z_Litros': '{:+.2f}', 'Z_CxL': '{:+.2f}',
    }
    fmt = {k: v for k, v in fmt.items() if k in df_show.columns}
    styled = df_show.style.format(fmt)
    if 'Severidad' in df_show.columns:
        styled = styled.map(colorear_severidad, subset=['Severidad'])
    for col in ['Z_Flete', 'Z_Litros', 'Z_CxL']:
        if col in df_show.columns:
            styled = styled.map(colorear_z, subset=[col])
    st.dataframe(styled, use_container_width=True, height=400)

    csv = df_show.to_csv(index=False).encode('utf-8')
    st.download_button("📥 Descargar como CSV", csv, "anomalias_flete.csv", "text/csv", key="dl_t1")

    # Diagnósticos detallados
    if len(df_anom[df_anom['Es Anomalía'] == 1]) > 0:
        st.markdown("---")
        st.subheader("🔍 Diagnósticos detallados")
        df_diag = df_anom[df_anom['Es Anomalía'] == 1].sort_values(
            by='Severidad', key=lambda x: x.map({'ALTO': 0, 'MEDIO': 1})
        ).head(10)
        for _, row in df_diag.iterrows():
            cls = 'severidad-alto' if row['Severidad'] == 'ALTO' else 'severidad-medio'
            fecha_str = row['Fecha Factura'].strftime("%d/%m/%Y") if pd.notna(row['Fecha Factura']) else "N/A"
            st.markdown(
                f'<div class="{cls}"><strong>{row["Nombre de Cliente"]}</strong> · '
                f'{fecha_str} · Remisión {row.get("Remisión", "N/A")}<br>'
                f'<small>{row["Diagnóstico"]}</small></div>',
                unsafe_allow_html=True
            )

    # Top clientes con anomalías
    st.markdown("---")
    st.subheader("📊 Top clientes con anomalías")
    cli_anom = df_filtrado[df_filtrado['Es Anomalía'] == 1].groupby('Nombre de Cliente').agg(
        Anomalias=('Es Anomalía', 'sum'),
        Flete_Total=('Flete', 'sum')
    ).reset_index().sort_values('Anomalias', ascending=False).head(15)

    if len(cli_anom) > 0:
        fig_cli = go.Figure(go.Bar(
            y=cli_anom['Nombre de Cliente'], x=cli_anom['Anomalias'],
            orientation='h', marker_color='#DC2626',
            text=cli_anom['Anomalias'], textposition='outside',
            hovertemplate='<b>%{y}</b><br>Anomalías: %{x}<br>Flete Total: $%{customdata:,.0f}<extra></extra>',
            customdata=cli_anom['Flete_Total']
        ))
        fig_cli.update_layout(
            height=max(300, len(cli_anom) * 35),
            plot_bgcolor='white', paper_bgcolor='white',
            margin=dict(l=20, r=20, t=20, b=20),
            yaxis=dict(autorange='reversed'),
            xaxis=dict(title='Cantidad de anomalías')
        )
        st.plotly_chart(fig_cli, use_container_width=True)
    else:
        st.success("✅ No se detectaron anomalías con los filtros y umbrales actuales.")

    # Análisis individual por cliente
    st.markdown("---")
    st.subheader("📈 Análisis individual por cliente")

    cli_disp = df_filtrado[df_filtrado['Es Anomalía'] == 1]['Nombre de Cliente'].unique().tolist()
    cli_disp = sorted(cli_disp) if cli_disp else clientes

    if cli_disp:
        cli_det = st.selectbox("Selecciona un cliente", options=cli_disp, key="sel_cli_t1")
        df_c = df[df['Nombre de Cliente'] == cli_det].sort_values('Fecha Factura')

        if len(df_c) > 0:
            ca, cb, cc, cd = st.columns(4)
            with ca:
                st.metric("Registros", f"{len(df_c)}")
            with cb:
                st.metric("Flete promedio", f"${df_c['Flete'].mean():,.0f}")
            with cc:
                st.metric("CxL promedio", f"${df_c['Costo por Litro'].mean():.2f}")
            with cd:
                st.metric("Anomalías", f"{int(df_c['Es Anomalía'].sum())}")

            fig_i = make_subplots(
                rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.08,
                subplot_titles=('Flete pagado', 'Litros facturados',
                                'Costo por Litro (con bandas ±1σ y ±2σ)'),
                row_heights=[0.32, 0.32, 0.36]
            )

            es_a = df_c['Es Anomalía'] == 1
            cl_a = ['#DC2626' if a else '#1E3A8A' for a in es_a]
            sz_a = [12 if a else 6 for a in es_a]

            fig_i.add_trace(go.Scatter(
                x=df_c['Fecha Factura'], y=df_c['Flete'], mode='lines+markers',
                line=dict(color='#1E3A8A', width=2),
                marker=dict(size=sz_a, color=cl_a),
                customdata=df_c[['Remisión', 'Folio NC', 'Proveedor transporte']].fillna('N/A').values,
                hovertemplate=('<b>%{x|%d/%m/%Y}</b><br>Flete: $%{y:,.0f}<br>'
                               'Remisión: %{customdata[0]}<br>Folio NC: %{customdata[1]}<br>'
                               'Proveedor: %{customdata[2]}<extra></extra>'),
                showlegend=False
            ), row=1, col=1)
            mf = df_c['Flete'].mean()
            fig_i.add_hline(y=mf, line_dash="dash", line_color="#888780",
                            annotation_text=f"Media: ${mf:,.0f}", annotation_position="right",
                            row=1, col=1)

            fig_i.add_trace(go.Scatter(
                x=df_c['Fecha Factura'], y=df_c['Litros Fact'], mode='lines+markers',
                line=dict(color='#10B981', width=2), marker=dict(size=6, color='#10B981'),
                customdata=df_c[['Remisión', 'Folio NC', 'Proveedor transporte']].fillna('N/A').values,
                hovertemplate=('<b>%{x|%d/%m/%Y}</b><br>Litros: %{y:,.0f}<br>'
                               'Remisión: %{customdata[0]}<br>Folio NC: %{customdata[1]}<br>'
                               'Proveedor: %{customdata[2]}<extra></extra>'),
                showlegend=False
            ), row=2, col=1)
            ml = df_c['Litros Fact'].mean()
            fig_i.add_hline(y=ml, line_dash="dash", line_color="#888780",
                            annotation_text=f"Media: {ml:,.0f}", annotation_position="right",
                            row=2, col=1)

            mc = df_c['Costo por Litro'].mean()
            sc = df_c['Costo por Litro'].std()
            b2s = mc + 2 * sc;
            b2i = max(mc - 2 * sc, 0)
            b1s = mc + sc;
            b1i = max(mc - sc, 0)
            fechas = df_c['Fecha Factura'].tolist()

            fig_i.add_trace(go.Scatter(x=fechas, y=[b2s] * len(fechas), mode='lines',
                                       line=dict(color='#DC2626', width=1, dash='dot'),
                                       hovertemplate=f'+2σ: ${b2s:.2f}<extra></extra>',
                                       showlegend=False), row=3, col=1)
            fig_i.add_trace(go.Scatter(x=fechas, y=[b2i] * len(fechas), mode='lines',
                                       line=dict(color='#DC2626', width=1, dash='dot'),
                                       fill='tonexty', fillcolor='rgba(220, 38, 38, 0.05)',
                                       hovertemplate=f'-2σ: ${b2i:.2f}<extra></extra>',
                                       showlegend=False), row=3, col=1)
            fig_i.add_trace(go.Scatter(x=fechas, y=[b1s] * len(fechas), mode='lines',
                                       line=dict(color='#F59E0B', width=1, dash='dash'),
                                       hovertemplate=f'+1σ: ${b1s:.2f}<extra></extra>',
                                       showlegend=False), row=3, col=1)
            fig_i.add_trace(go.Scatter(x=fechas, y=[b1i] * len(fechas), mode='lines',
                                       line=dict(color='#F59E0B', width=1, dash='dash'),
                                       fill='tonexty', fillcolor='rgba(16, 185, 129, 0.08)',
                                       hovertemplate=f'-1σ: ${b1i:.2f}<extra></extra>',
                                       showlegend=False), row=3, col=1)
            fig_i.add_hline(y=mc, line_dash="dash", line_color="#475569",
                            annotation_text=f"Media: ${mc:.2f}", annotation_position="right",
                            row=3, col=1)

            cxl_v = df_c['Costo por Litro'].values
            cl_c = [];
            sz_c = []
            for v in cxl_v:
                if v > b2s or v < b2i:
                    cl_c.append('#DC2626');
                    sz_c.append(12)
                elif v > b1s or v < b1i:
                    cl_c.append('#F59E0B');
                    sz_c.append(8)
                else:
                    cl_c.append('#1E3A8A');
                    sz_c.append(6)

            fig_i.add_trace(go.Scatter(
                x=df_c['Fecha Factura'], y=df_c['Costo por Litro'], mode='lines+markers',
                line=dict(color='#1E3A8A', width=2.5),
                marker=dict(size=sz_c, color=cl_c, line=dict(color=cl_c, width=1)),
                customdata=df_c[['Remisión', 'Folio NC', 'Flete', 'Litros Fact',
                                 'Proveedor transporte']].fillna('N/A').values,
                hovertemplate=('<b>%{x|%d/%m/%Y}</b><br>$/L: $%{y:.2f}<br>'
                               'Remisión: %{customdata[0]}<br>Folio NC: %{customdata[1]}<br>'
                               'Flete: $%{customdata[2]:,.0f}<br>Litros: %{customdata[3]:,.0f}<br>'
                               'Proveedor: %{customdata[4]}<extra></extra>'),
                showlegend=False
            ), row=3, col=1)

            fig_i.update_layout(height=700, showlegend=False,
                                plot_bgcolor='white', paper_bgcolor='white',
                                margin=dict(l=20, r=80, t=40, b=20), hovermode='x unified')
            fig_i.update_xaxes(showgrid=False)
            fig_i.update_yaxes(showgrid=True, gridcolor='#F1F5F9')
            fig_i.update_yaxes(title_text='$', row=1, col=1)
            fig_i.update_yaxes(title_text='L', row=2, col=1)
            fig_i.update_yaxes(title_text='$/L', row=3, col=1)
            st.plotly_chart(fig_i, use_container_width=True)

            cl1, cl2, cl3 = st.columns(3)
            with cl1:
                st.markdown('<div style="background:rgba(16,185,129,0.15);padding:8px 12px;'
                            'border-radius:8px;border-left:4px solid #10B981;font-size:13px;">'
                            '🟢 <strong>Zona normal</strong> (±1σ): comportamiento esperado</div>',
                            unsafe_allow_html=True)
            with cl2:
                st.markdown('<div style="background:rgba(245,158,11,0.15);padding:8px 12px;'
                            'border-radius:8px;border-left:4px solid #F59E0B;font-size:13px;">'
                            '🟡 <strong>Zona de alerta</strong> (1σ–2σ): elevado pero no crítico</div>',
                            unsafe_allow_html=True)
            with cl3:
                st.markdown('<div style="background:rgba(220,38,38,0.15);padding:8px 12px;'
                            'border-radius:8px;border-left:4px solid #DC2626;font-size:13px;">'
                            '🔴 <strong>Zona crítica</strong> (>2σ): anomalía estadística</div>',
                            unsafe_allow_html=True)

# ╔══════════════════════════════════════════════════════════╗
# ║  PESTAÑA 2 — FACTURAS SIN MATCH EN SAP                   ║
# ╚══════════════════════════════════════════════════════════╝
with tab2:
    st.markdown("**Conciliación entre facturas de transporte y SAP** — detecta errores de captura, "
                "facturas faltantes y discrepancias de monto.")

    # Alerta explicativa
    st.markdown("""
    <div style="
        background: linear-gradient(135deg, #DBEAFE 0%, #BFDBFE 100%);
        border-left: 6px solid #1E3A8A;
        padding: 16px 20px;
        border-radius: 12px;
        margin: 16px 0;
    ">
        <div style="font-size: 16px; font-weight: 600; color: #1E3A8A; margin-bottom: 8px;">
            ℹ️ Cómo se hace la conciliación
        </div>
        <div style="color: #1E3A8A; line-height: 1.6;">
            Para cada factura de transporte registrada en <em>Logística Nac</em>, el sistema busca su 
            <strong>match exacto en SAP proveedores</strong>. Si no la encuentra, intenta resolver 
            mediante similitud textual (errores de captura) y por monto. Cada registro recibe una 
            categoría que indica la naturaleza de la discrepancia y una explicación humana de la causa.
            <br><br>
            Las filas con <strong>proveedor "CLIENTE"</strong> y las que tienen la columna 
            <em>Factura transporte</em> vacía se omiten automáticamente.
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Sidebar específico de tab2
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🔎 Pestaña: Facturas vs SAP")
    tolerancia = st.sidebar.number_input(
        "Tolerancia de monto ($)", min_value=0.0, max_value=100.0, value=1.0, step=0.5,
        help="Diferencia máxima en pesos para considerar que un monto coincide"
    )

    # Ejecutar auditoría
    with st.spinner("🔄 Cruzando facturas con SAP..."):
        df_audit = auditar_facturas(df_log_raw, df_sap, tolerancia_monto=tolerancia)

    if len(df_audit) == 0:
        st.warning("No se encontraron registros válidos para auditar.")
    else:
        # KPIs de la pestaña 2
        n_total = len(df_audit)
        n_ok = (df_audit['Categoría'] == 'COINCIDE_EXACTO').sum()
        n_provision = (df_audit['Categoría'] == 'PROVISION').sum()
        n_problemas = n_total - n_ok - n_provision
        n_typos = df_audit['Categoría'].isin(
            ['TYPO_CON_MONTO_COINCIDENTE', 'UUID_TYPO_CON_MONTO_COINCIDENTE']
        ).sum()

        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
        with kpi1:
            st.metric("📊 Facturas auditadas", f"{n_total:,}")
        with kpi2:
            st.metric("✅ Match exacto", f"{n_ok:,}")
        with kpi3:
            st.metric("⚠️ Con discrepancias", f"{n_problemas:,}")
        with kpi4:
            st.metric("🟢 Errores de captura confirmados", f"{n_typos:,}")

        st.markdown("---")

        # Resumen por categoría
        st.subheader("📋 Resumen por categoría")
        resumen = df_audit['Categoría'].value_counts().reset_index()
        resumen.columns = ['Categoría', 'Cantidad']
        resumen['Etiqueta'] = resumen['Categoría'].map(
            lambda c: CATEGORIAS_INFO.get(c, {}).get('label', c)
        )
        resumen['Descripción'] = resumen['Categoría'].map(
            lambda c: CATEGORIAS_INFO.get(c, {}).get('desc', '')
        )

        # Mostrar como cards
        for _, row in resumen.iterrows():
            info = CATEGORIAS_INFO.get(row['Categoría'], {})
            color = info.get('color', '#475569')
            bg = info.get('bg', '#F1F5F9')
            label = info.get('label', row['Categoría'])
            desc = info.get('desc', '')
            st.markdown(f"""
            <div style="
                background: {bg};
                border-left: 5px solid {color};
                padding: 12px 16px;
                border-radius: 8px;
                margin: 6px 0;
                display: flex;
                justify-content: space-between;
                align-items: center;
            ">
                <div style="flex: 1;">
                    <div style="font-weight: 600; color: {color}; font-size: 15px;">
                        {label}
                    </div>
                    <div style="color: #475569; font-size: 12px; margin-top: 4px;">
                        {desc}
                    </div>
                </div>
                <div style="
                    background: {color}; color: white; 
                    padding: 8px 16px; border-radius: 8px;
                    font-weight: 700; font-size: 18px; min-width: 60px; text-align: center;
                ">
                    {row['Cantidad']}
                </div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("---")

        # Filtros de tabla
        st.subheader("🔍 Detalle de registros con discrepancias")

        col_f1, col_f2, col_f3 = st.columns([2, 2, 1])
        with col_f1:
            cat_disp = sorted([c for c in df_audit['Categoría'].unique()
                               if c not in ['COINCIDE_EXACTO', 'PROVISION']])
            cat_sel = st.multiselect(
                "Filtrar por categoría",
                options=cat_disp,
                default=cat_disp,
                format_func=lambda c: CATEGORIAS_INFO.get(c, {}).get('label', c)
            )
        with col_f2:
            prov_uniq = sorted(df_audit['Proveedor transporte'].dropna().unique())
            prov_sel = st.multiselect("Filtrar por proveedor", options=prov_uniq, default=[])
        with col_f3:
            ocultar_ok = st.checkbox("Ocultar matches OK", value=True, key="ocultar_ok_t2")

        df_show2 = df_audit.copy()
        if ocultar_ok:
            df_show2 = df_show2[~df_show2['Categoría'].isin(['COINCIDE_EXACTO', 'PROVISION'])]
        if cat_sel and not ocultar_ok:
            df_show2 = df_show2[df_show2['Categoría'].isin(cat_sel + ['COINCIDE_EXACTO', 'PROVISION'])]
        elif cat_sel:
            df_show2 = df_show2[df_show2['Categoría'].isin(cat_sel)]
        if prov_sel:
            df_show2 = df_show2[df_show2['Proveedor transporte'].isin(prov_sel)]

        st.info(f"📌 Mostrando **{len(df_show2)}** registros")

        # Renombrar categoría para usuario
        df_show2 = df_show2.copy()
        df_show2['Categoría (humana)'] = df_show2['Categoría'].map(
            lambda c: CATEGORIAS_INFO.get(c, {}).get('label', c)
        )

        # Columnas a mostrar
        cols_audit = [
            'Fecha Factura', 'Nombre de Cliente', 'Remisión',
            'factura_evaluada', 'Proveedor transporte',
            'Total Flete ', 'Total Flete',
            'Categoría (humana)', 'Razón de No Coincidencia'
        ]
        cols_audit = [c for c in cols_audit if c in df_show2.columns]
        df_view = df_show2[cols_audit].copy()
        if 'Fecha Factura' in df_view.columns:
            df_view['Fecha Factura'] = pd.to_datetime(df_view['Fecha Factura'], errors='coerce').dt.strftime('%d/%m/%Y')


        def colorear_cat(val):
            for k, info in CATEGORIAS_INFO.items():
                if info['label'] == val:
                    return f'background-color: {info["bg"]}; color: {info["color"]}; font-weight: 600;'
            return ''


        fmt2 = {}
        if 'Total Flete' in df_view.columns: fmt2['Total Flete'] = '${:,.2f}'
        if 'Total Flete ' in df_view.columns: fmt2['Total Flete '] = '${:,.2f}'

        styled2 = df_view.style.format(fmt2)
        if 'Categoría (humana)' in df_view.columns:
            styled2 = styled2.map(colorear_cat, subset=['Categoría (humana)'])

        st.dataframe(styled2, use_container_width=True, height=500)

        # Descarga
        csv2 = df_view.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Descargar resultados como CSV", csv2,
                           "auditoria_facturas_sap.csv", "text/csv", key="dl_t2")

        # Diagnósticos detallados de los casos más críticos
        st.markdown("---")
        st.subheader("🔍 Casos a revisar prioritariamente")

        # Casos prioritarios: los que tienen monto coincidente (alta confianza de typo)
        criticos = df_audit[df_audit['Categoría'].isin([
            'TYPO_CON_MONTO_COINCIDENTE', 'UUID_TYPO_CON_MONTO_COINCIDENTE'
        ])].head(15)

        if len(criticos) > 0:
            st.markdown("**Errores de captura con alta confianza** (monto coincide exactamente):")
            for _, row in criticos.iterrows():
                info = CATEGORIAS_INFO.get(row['Categoría'], {})
                fecha_str = pd.to_datetime(row['Fecha Factura'], errors='coerce')
                fecha_str = fecha_str.strftime("%d/%m/%Y") if pd.notna(fecha_str) else "N/A"
                st.markdown(f"""
                <div style="
                    background: {info.get('bg', '#F0FDF4')};
                    border-left: 4px solid {info.get('color', '#16A34A')};
                    padding: 12px 16px;
                    border-radius: 8px;
                    margin: 6px 0;
                ">
                    <div style="font-weight: 600; color: {info.get('color', '#16A34A')};">
                        {row.get('Nombre de Cliente', 'N/A')} · {fecha_str} · 
                        Remisión {row.get('Remisión', 'N/A')}
                    </div>
                    <div style="color: #1E293B; font-size: 13px; margin-top: 4px; line-height: 1.5;">
                        {row.get('Razón de No Coincidencia', '')}
                    </div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.success("✅ No se detectaron errores de captura con monto coincidente.")

# ============================================================
# FOOTER
# ============================================================
st.markdown("---")
st.caption(
    "💡 **Dashboard de Auditoría Logística** · "
    "Análisis estadístico de fletes (Z-scores por cliente) + "
    "Conciliación SAP con detección de errores de captura"
)
