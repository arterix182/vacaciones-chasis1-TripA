import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import datetime as dt
import calendar
import html as html_lib
from io import BytesIO
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, DataReturnMode, JsCode

from storage_gsheets_v4_18 import (
    get_empleados_dict, get_empleados_df, get_agenda_df,
    append_agenda_row_safe, append_agenda_row_admin,
    delete_agenda_rows, replace_empleados_df, append_empleados_rows,
    set_admin_incidence, get_requerimientos_df, replace_requerimientos_df
)

st.set_page_config(page_title="Vacaciones CH-1", page_icon="📅", layout="wide")

MESES = ["Enero","Febrero","Marzo","Abril","Mayo","Junio","Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"]

ADMIN_PASSWORD = st.secrets.get("admin_password", "CH1-Admin-2025")

TEAM_ORDER = [
    "La Flota",
    "Underzide B",
    "007 Delta",
    "Logianos",
    "Spartans B",
    "Dragon Force",
    "Supremos",
    "Little Boys",
]
TEAM_RANK = {name.lower(): i for i, name in enumerate(TEAM_ORDER)}

# Alias frecuentes para que variantes escritas en Google Sheets no creen equipos duplicados.
TEAM_ALIASES = {
    "la flota": "La Flota",
    "flota": "La Flota",
    "underzide b": "Underzide B",
    "under zide b": "Underzide B",
    "underzide": "Underzide B",
    "under zide": "Underzide B",
    "007 delta": "007 Delta",
    "logianos": "Logianos",
    "spartans b": "Spartans B",
    "spartans": "Spartans B",
    "espartans": "Spartans B",
    "espartans b": "Spartans B",
    "dragon force": "Dragon Force",
    "supremos": "Supremos",
    "little boys": "Little Boys",
}

def canonical_team(value):
    raw = " ".join(str(value or "").strip().split())
    key = raw.lower()
    return TEAM_ALIASES.get(key, raw)

def is_operational_team(value):
    return canonical_team(value).lower() in TEAM_RANK

FUNCIONES = ["LET", "MET", "POOL"]
FUNCION_COLORS = {"LET":"#06b6d4", "MET":"#8b5cf6", "POOL":"#f59e0b", "":"#64748b"}
# Incidencias que hacen que una persona no cuente como disponible para la línea ese día.
# RET y TRB sí se consideran disponibles.
NO_DISPONIBLE = {"VAC","PSG","PPSG","FI","FJ","SAN","DEF","PAT","INC","SM","RM","EM","BJ","TE","PT"}

# ============================================================
# CALENDARIO LABORAL CHASIS 1 — CICLO EXACTO DE 4 SEMANAS
# ============================================================
# Python: lunes=0 ... domingo=6
TURNOS_DIAS = {
    "PRIMER TURNO": {0, 1, 2, 3},       # Lun-Mar-Mié-Jue
    "TURNO MIXTO": {0, 1, 4, 5},        # Lun-Mar-Vie-Sáb
    "TURNO NOCTURNO": {2, 3, 4, 5},     # Mié-Jue-Vie-Sáb
}

COLOR_TRABAJO = "#0e7490"
COLOR_TRABAJO_CELL = "#123447"
COLOR_DESCANSO = "#334155"
COLOR_DESCANSO_CELL = "#111827"
COLOR_CAMBIO = "#92400e"
COLOR_CAMBIO_CELL = "#2b1d12"

# Ancla confirmada:
# 02-nov-2026 inicia TURNO MIXTO.
# Desde aquí el ciclo SIEMPRE es:
#   28 días MIXTO
#   28 días PRIMER TURNO
#   28 días NOCTURNO
# Total = 84 días.
#
# El descanso especial de 5 días ocurre al pasar de PRIMER a NOCTURNO:
# viernes de la 4ª semana del Primer Turno hasta martes de la 1ª semana Nocturna.
# Es decir, dentro de cada ciclo: offsets 53,54,55,56,57.
CICLO_ANCLA = dt.date(2026, 11, 2)
CICLO_DIAS = 84

def info_calendario_laboral(fecha):
    """
    Calendario cíclico exacto:
      0-27  -> TURNO MIXTO
      28-55 -> PRIMER TURNO
      56-83 -> TURNO NOCTURNO

    Descanso especial:
      offsets 53-57 (5 días: viernes a martes), superpuesto entre
      el cierre del Primer Turno y el arranque del Nocturno.

    Esto conserva 4 semanas exactas por turno.
    """
    if isinstance(fecha, pd.Timestamp):
        fecha = fecha.date()

    # Antes del ancla usamos el nocturno previo conocido.
    if fecha < CICLO_ANCLA:
        # Semana conocida: 26-oct a 01-nov era la última nocturna.
        # Extendemos hacia atrás con el mismo patrón nocturno solo para esa semana.
        if dt.date(2026, 10, 26) <= fecha <= dt.date(2026, 11, 1):
            turno = "TURNO NOCTURNO"
            trabaja = fecha.weekday() in TURNOS_DIAS[turno]
            return {
                "turno": turno,
                "trabaja": trabaja,
                "cambio": False,
                "color": COLOR_TRABAJO if trabaja else COLOR_DESCANSO,
                "cell_color": COLOR_TRABAJO_CELL if trabaja else COLOR_DESCANSO_CELL,
            }
        return {
            "turno": "SIN CALENDARIO",
            "trabaja": False,
            "cambio": False,
            "color": COLOR_DESCANSO,
            "cell_color": COLOR_DESCANSO_CELL,
        }

    pos = (fecha - CICLO_ANCLA).days % CICLO_DIAS

    # 5 días especiales: viernes-sábado-domingo-lunes-martes.
    if 53 <= pos <= 57:
        return {
            "turno": "DESCANSO CAMBIO",
            "trabaja": False,
            "cambio": True,
            "color": COLOR_CAMBIO,
            "cell_color": COLOR_CAMBIO_CELL,
        }

    if pos <= 27:
        turno = "TURNO MIXTO"
    elif pos <= 55:
        turno = "PRIMER TURNO"
    else:
        turno = "TURNO NOCTURNO"

    trabaja = fecha.weekday() in TURNOS_DIAS[turno]

    return {
        "turno": turno,
        "trabaja": trabaja,
        "cambio": False,
        "color": COLOR_TRABAJO if trabaja else COLOR_DESCANSO,
        "cell_color": COLOR_TRABAJO_CELL if trabaja else COLOR_DESCANSO_CELL,
    }


def periodos_laborales_mes(anio, mes):
    """Agrupa días consecutivos con el mismo turno dentro del mes."""
    ultimo = calendar.monthrange(int(anio), int(mes))[1]
    periodos = []
    inicio = None
    turno_actual = None

    for d in range(1, ultimo + 1):
        f = dt.date(int(anio), int(mes), d)
        turno = info_calendario_laboral(f)["turno"]
        if turno != turno_actual:
            if turno_actual is not None:
                periodos.append((inicio, d - 1, turno_actual))
            inicio = d
            turno_actual = turno
    if turno_actual is not None:
        periodos.append((inicio, ultimo, turno_actual))
    return periodos


# Diseño general — V4.6
st.markdown("""
<style>
    /* Evita que la barra superior de Streamlit tape las pestañas */
    .block-container {
        padding-top: 4.4rem !important;
        padding-bottom: 2.5rem !important;
        max-width: 1900px !important;
        width: calc(100% - 32px) !important;
        margin: 0 auto !important;
    }

    /* Pestañas: completas, legibles y con scroll horizontal si hace falta */
    div[data-baseweb="tab-list"] {
        gap: 8px !important;
        overflow-x: auto !important;
        overflow-y: visible !important;
        padding: 10px 6px 12px 6px !important;
        margin: 0 0 18px 0 !important;
        scrollbar-width: thin;
        scrollbar-color: #475569 #111827;
        background: rgba(11,18,32,.94);
        border: 1px solid #26364f;
        border-radius: 14px;
        box-shadow: 0 10px 28px rgba(2,6,23,.18);
    }
    button[data-baseweb="tab"] {
        flex: 0 0 auto !important;
        min-height: 48px !important;
        padding: 0 16px !important;
        border-radius: 10px 10px 6px 6px !important;
        white-space: nowrap !important;
        overflow: visible !important;
    }
    button[data-baseweb="tab"] p {
        font-size: 15px !important;
        line-height: 1.2 !important;
        font-weight: 800 !important;
        white-space: nowrap !important;
        overflow: visible !important;
    }
    button[data-baseweb="tab"][aria-selected="true"] {
        background: linear-gradient(180deg, rgba(37,99,235,.20), rgba(15,23,42,.10)) !important;
    }

    /* Títulos más ordenados */
    h1, h2, h3 {
        letter-spacing: -0.02em;
    }

    /* Hero principal */
    .matrix-hero {
        padding: 20px 24px;
        border-radius: 18px;
        background: linear-gradient(120deg,#0f172a 0%,#172554 48%,#0c4a6e 100%);
        border: 1px solid rgba(56,189,248,.30);
        box-shadow: 0 16px 44px rgba(2,6,23,.28);
        margin: 0 0 18px 0;
    }
    .matrix-title {
        font-size: 26px;
        line-height: 1.15;
        font-weight: 900;
        color:#f8fafc;
        margin:0;
    }
    .matrix-sub {
        color:#bae6fd;
        margin-top:7px;
        font-size:13px;
        line-height:1.45;
    }

    /* Paneles de resumen: reemplazan filas desparejas de métricas */
    .dashboard-panel {
        background: linear-gradient(145deg,#101a2d,#162238);
        border: 1px solid #2b405f;
        border-radius: 16px;
        padding: 10px 14px 12px 14px;
        margin: 10px 0 12px 0;
        box-shadow: 0 10px 26px rgba(2,6,23,.20);
    }
    .dashboard-panel-title {
        color:#93c5fd;
        font-size:12px;
        font-weight:900;
        letter-spacing:.08em;
        text-transform:uppercase;
        margin-bottom:10px;
    }
    .dashboard-kpis {
        display:grid;
        grid-template-columns:repeat(auto-fit,minmax(140px,1fr));
        gap:10px;
    }
    .dashboard-kpi {
        min-height:58px;
        background:rgba(15,23,42,.72);
        border:1px solid #334155;
        border-radius:12px;
        padding:10px 12px;
        display:flex;
        flex-direction:column;
        justify-content:center;
    }
    .dashboard-kpi-label {
        color:#94a3b8;
        font-size:11px;
        font-weight:700;
        margin-bottom:4px;
    }
    .dashboard-kpi-value {
        color:#f8fafc;
        font-size:21px;
        font-weight:950;
        line-height:1;
    }

    .hint-box {
        background:rgba(14,116,144,.12);
        border:1px solid rgba(34,211,238,.28);
        border-radius:14px;
        padding:11px 14px;
        margin:10px 0 16px 0;
        color:#cffafe;
        font-size:12px;
        line-height:1.45;
    }

    /* Evitar controles excesivamente estirados */
    div[data-testid="stTextInput"] input,
    div[data-testid="stSelectbox"] > div > div,
    div[data-testid="stNumberInput"] input {
        min-height: 42px;
    }

    @media (max-width: 900px) {
        .block-container {
            padding-top: 5.2rem !important;
            width: calc(100% - 18px) !important;
        }
        button[data-baseweb="tab"] {
            min-height: 50px !important;
            padding: 0 14px !important;
        }
        button[data-baseweb="tab"] p {
            font-size: 14px !important;
        }
        .matrix-title { font-size:22px; }
        .dashboard-kpis {
            grid-template-columns:repeat(2,minmax(0,1fr));
        }
    }
</style>
""", unsafe_allow_html=True)

INCIDENCIAS = {
    "VAC": ("Vacaciones", "#10b981"),
    "PSG": ("Permiso Sin Goce", "#fbbf24"),
    "PPSG": ("Permiso Parcial Sin Goce", "#f59e0b"),
    "FI": ("Falta Injustificada", "#ef4444"),
    "FJ": ("Falta Justificada", "#facc15"),
    "SAN": ("Sanción", "#dc2626"),
    "RET": ("Retardo", "#2563eb"),
    "DEF": ("Permiso por Defunción", "#64748b"),
    "PAT": ("Permiso por Paternidad", "#0ea5e9"),
    "INC": ("Incapacidad", "#a855f7"),
    "SM": ("Servicio Médico", "#ec4899"),
    "RM": ("Restricción Médica", "#14b8a6"),
    "EM": ("Embarazada", "#d946ef"),
    "BJ": ("Baja", "#6b7280"),
    "TE": ("Soporte TE", "#60a5fa"),
    "PT": ("Paro Técnico", "#f97316"),
    "TRB": ("Trabajado", "#15803d"),
}

TIPO_A_CODIGO = {
    "Vacaciones": "VAC", "Permiso": "PSG", "Permiso Sin Goce": "PSG",
    "Permiso Parcial Sin Goce": "PPSG", "Sanción": "SAN", "Sancion": "SAN",
    "Falta Injustificada": "FI", "Falta Justificada": "FJ", "Retardo": "RET",
    "Permiso por Defunción": "DEF", "Permiso por Defuncion": "DEF",
    "Permiso por Paternidad": "PAT", "Incapacidad": "INC", "Servicio Médico": "SM",
    "Servicio Medico": "SM", "Restricción Médica": "RM", "Restriccion Medica": "RM",
    "Embarazada": "EM", "Baja": "BJ", "Soporte TE": "TE", "Paro Técnico": "PT",
    "Paro Tecnico": "PT", "Trabajado": "TRB",
}

def codigo_tipo(tipo):
    t = str(tipo).strip()
    if t in INCIDENCIAS:
        return t
    return TIPO_A_CODIGO.get(t, t[:4].upper() if t else "?")

def etiqueta_tipo(tipo):
    cod = codigo_tipo(tipo)
    return INCIDENCIAS.get(cod, (str(tipo), "#475569"))[0]

def color_tipo(tipo):
    cod = codigo_tipo(tipo)
    return INCIDENCIAS.get(cod, (str(tipo), "#475569"))[1]


def calcular_cobertura_equipo(team_staff, unavailable_nums, req_met=0):
    """
    Lógica operativa CHASIS 1:
    - Los MET son la plantilla base que cubre las estaciones.
    - POOL es respaldo EXTRA y cubre la primera ausencia de un MET.
    - LET es respaldo EXTRA y cubre la segunda ausencia de un MET.
    - Una incidencia del propio POOL o LET los vuelve indisponibles,
      pero NO crea un hueco de estación MET.
    """
    if team_staff is None or team_staff.empty:
        return {
            "incidencias": 0,
            "ausencias_met": 0,
            "pool_cubre": 0,
            "let_cubre": 0,
            "let_libre": 0,
            "pool_libre": 0,
            "met_faltantes": 0,
            "estado": "⚪ SIN PERSONAL",
        }

    tdf = team_staff.copy()
    tdf["funcion"] = tdf["funcion"].astype(str).str.strip().str.upper()
    nums = tdf["numero"].astype(str).str.strip()
    unavailable_nums = set(str(x).strip() for x in unavailable_nums)

    incidencias = int(nums.isin(unavailable_nums).sum())

    # Solo la ausencia de un MET deja una estación descubierta.
    ausencias_met = int(
        ((tdf["funcion"] == "MET") & nums.isin(unavailable_nums)).sum()
    )

    pool_disponible = int(
        ((tdf["funcion"] == "POOL") & ~nums.isin(unavailable_nums)).sum()
    )
    let_disponible = int(
        ((tdf["funcion"] == "LET") & ~nums.isin(unavailable_nums)).sum()
    )

    # Prioridad: POOL primero, LET después.
    pool_cubre = min(pool_disponible, ausencias_met)
    pendiente = max(ausencias_met - pool_cubre, 0)

    let_cubre = min(let_disponible, pendiente)
    met_faltantes = max(pendiente - let_cubre, 0)

    pool_libre = max(pool_disponible - pool_cubre, 0)
    let_libre = max(let_disponible - let_cubre, 0)

    if int(req_met) <= 0:
        estado = "⚪ SIN REQUERIMIENTO"
    elif met_faltantes > 0:
        estado = f"🔴 NECESITA {met_faltantes} MET"
    else:
        estado = "🟢 CUBIERTO"

    return {
        "incidencias": incidencias,
        "ausencias_met": ausencias_met,
        "pool_cubre": pool_cubre,
        "let_cubre": let_cubre,
        "let_libre": let_libre,
        "pool_libre": pool_libre,
        "met_faltantes": met_faltantes,
        "estado": estado,
    }


def render_kpi_panel(title, items):
    cards = []
    for label, value in items:
        cards.append(
            f"<div class='dashboard-kpi'>"
            f"<div class='dashboard-kpi-label'>{html_lib.escape(str(label))}</div>"
            f"<div class='dashboard-kpi-value'>{html_lib.escape(str(value))}</div>"
            f"</div>"
        )
    st.markdown(
        f"<div class='dashboard-panel'>"
        f"<div class='dashboard-panel-title'>{html_lib.escape(str(title))}</div>"
        f"<div class='dashboard-kpis'>{''.join(cards)}</div>"
        f"</div>",
        unsafe_allow_html=True
    )

@st.cache_data(ttl=300)
def load_empleados():
    return get_empleados_dict()

@st.cache_data(ttl=300)
def load_empleados_df():
    return get_empleados_df()

@st.cache_data(ttl=60)
def load_agenda():
    df = get_agenda_df()
    if df is None or df.empty:
        return pd.DataFrame(columns=["numero","nombre","equipo","fecha","tipo","_sheet_row"])
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    return df.dropna(subset=["fecha"])

@st.cache_data(ttl=300)
def load_requerimientos():
    df = get_requerimientos_df()
    if df is None or df.empty:
        return pd.DataFrame(columns=["equipo","let_requeridos","met_requeridos"])
    df = df.copy()
    df["equipo"] = df["equipo"].astype(str).str.strip()
    df["let_requeridos"] = pd.to_numeric(df["let_requeridos"], errors="coerce").fillna(0).astype(int)
    df["met_requeridos"] = pd.to_numeric(df["met_requeridos"], errors="coerce").fillna(0).astype(int)
    return df

def clear_agenda_cache():
    load_agenda.clear()

def clear_empleados_cache():
    load_empleados.clear()
    load_empleados_df.clear()

def clear_requerimientos_cache():
    load_requerimientos.clear()

def clear_cache():
    clear_empleados_cache()
    clear_agenda_cache()
    clear_requerimientos_cache()

if "is_admin" not in st.session_state:
    st.session_state.is_admin = False

with st.sidebar:
    st.title("Vacaciones CH-1")
    with st.expander("🔑 Administrador", expanded=st.session_state.is_admin):
        if not st.session_state.is_admin:
            pwd = st.text_input("Contraseña admin", type="password", key="admin_pwd")
            if st.button("Entrar como admin", key="admin_login"):
                if pwd == ADMIN_PASSWORD:
                    st.session_state.is_admin = True
                    st.rerun()
                else:
                    st.error("Contraseña incorrecta")
        else:
            st.success("Modo administrador activo")
            if st.button("Cerrar sesión", key="admin_logout"):
                st.session_state.is_admin = False
                st.rerun()

if st.session_state.is_admin:
    tab_cap, tab_cal, tab_matrix, tab_rep, tab_admin = st.tabs([
        "📝 Captura", "📅 Calendario", "🧩 Matriz de incidencias", "📊 Reportes", "🛠️ Administración"
    ])
else:
    tab_cap, tab_cal = st.tabs(["📝 Captura", "📅 Calendario"])
    tab_matrix = tab_rep = tab_admin = None

with tab_cap:
    st.header("Captura de solicitudes")
    empleados = load_empleados(); agenda = load_agenda()
    c1, c2 = st.columns(2)
    password = c1.text_input("Contraseña (usuario)", type="password", key="usr_pwd")
    numero = c2.text_input("Número de empleado", key="usr_num").strip()

    if password and numero in empleados:
        emp = empleados[numero]
        st.success(f"{emp['nombre']} — Equipo: {emp['equipo']} — Función: {emp.get('funcion') or 'SIN ASIGNAR'}")
        hoy = dt.date.today()
        a, m, d = st.columns(3)
        anio = a.number_input("Año", min_value=hoy.year, max_value=hoy.year+2, value=hoy.year, step=1, key="u_anio")
        mes = m.selectbox("Mes", range(1,13), index=hoy.month-1, format_func=lambda x: MESES[x-1], key="u_mes")
        ultimo = calendar.monthrange(int(anio), int(mes))[1]
        dia = d.selectbox("Día", range(1, ultimo+1), index=min(hoy.day-1, ultimo-1), key="u_dia")
        tipo_usr = st.selectbox("Tipo", ["Vacaciones", "Permiso", "Sanción"], key="u_tipo")
        fecha = dt.date(int(anio), int(mes), int(dia))
        mismos = agenda[agenda["fecha"].dt.date == fecha] if not agenda.empty else agenda.iloc[0:0]
        lleno = len(mismos) >= 3
        mismo_equipo = (not mismos.empty) and any(mismos["equipo"].astype(str).str.strip() == str(emp["equipo"]).strip())
        if lleno:
            st.warning("Seleccione otro día, ya que el día que solicitas ya está llena la agenda")
        elif mismo_equipo:
            st.warning("No puedes seleccionar este día porque ya hay alguien de tu equipo registrado")
        if st.button("Registrar día", key="u_registrar", disabled=(lleno or mismo_equipo)):
            try:
                append_agenda_row_safe({"numero": numero,"nombre": emp["nombre"],"equipo": emp["equipo"],"fecha": fecha.isoformat(),"tipo": tipo_usr})
                clear_agenda_cache(); st.success("Registro guardado"); st.rerun()
            except ValueError as e:
                if "LLENO" in str(e): st.warning("El día ya tiene 3 registros.")
                elif "MISMO_EQUIPO" in str(e): st.warning("Ya existe una persona de tu equipo en ese día.")
                else: st.error(f"No se pudo guardar: {e}")
        if not mismos.empty:
            st.subheader("Personas ya registradas ese día")
            st.dataframe(mismos[["numero","nombre","equipo","tipo"]], hide_index=True, use_container_width=True)
    else:
        if password and numero: st.error("Número de empleado no encontrado.")
        st.info("Ingresa contraseña y número de empleado.")

with tab_cal:
    st.markdown("""
    <div class="matrix-hero" style="margin-bottom:18px">
      <div class="matrix-title">📅 Calendario mensual</div>
      <div class="matrix-sub">Vista amplia de vacaciones e incidencias registradas. Desplázate horizontalmente en pantallas pequeñas.</div>
    </div>
    """, unsafe_allow_html=True)

    agenda = load_agenda()
    hoy = dt.date.today()

    a, m = st.columns([1,1])
    anio_c = a.number_input(
        "Año",
        value=hoy.year,
        min_value=hoy.year-1,
        max_value=hoy.year+3,
        key="c_anio"
    )
    mes_c = m.selectbox(
        "Mes",
        range(1,13),
        index=hoy.month-1,
        format_func=lambda x: MESES[x-1],
        key="c_mes"
    )

    if agenda.empty:
        dfm = agenda.copy()
        dfm["dia"] = []
        dfm["codigo"] = []
    else:
        mask = (
            (agenda["fecha"].dt.year == int(anio_c)) &
            (agenda["fecha"].dt.month == int(mes_c))
        )
        dfm = agenda[mask].copy()
        dfm["dia"] = dfm["fecha"].dt.day
        dfm["codigo"] = dfm["tipo"].apply(codigo_tipo)

    # Resumen mensual arriba del calendario
    total_mes_cal = len(dfm)
    dias_ocupados = int(dfm["dia"].nunique()) if not dfm.empty else 0
    dias_llenos = int((dfm.groupby("dia").size() >= 3).sum()) if not dfm.empty else 0
    vac_mes_cal = int((dfm["codigo"] == "VAC").sum()) if not dfm.empty else 0

    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("Registros del mes", total_mes_cal)
    mc2.metric("Días con registro", dias_ocupados)
    mc3.metric("Días con 3+", dias_llenos)
    mc4.metric("Vacaciones", vac_mes_cal)

    cal = calendar.Calendar(firstweekday=0)
    weeks = cal.monthdayscalendar(int(anio_c), int(mes_c))
    weekday_labels = ["LUN", "MAR", "MIÉ", "JUE", "VIE", "SÁB", "DOM"]

    # Agrupar registros por día para pintar nombres + tipo
    registros_por_dia = {}
    if not dfm.empty:
        for d, grp in dfm.sort_values(["dia","nombre"]).groupby("dia"):
            registros_por_dia[int(d)] = grp.to_dict("records")

    html_parts = ["""
    <html>
    <head>
    <style>
      * { box-sizing:border-box; }
      body {
        margin:0;
        background:#0b1220;
        color:#e5e7eb;
        font-family:Inter,Segoe UI,Arial,sans-serif;
      }
      .calendar-shell {
        width:100%;
        overflow-x:auto;
        overflow-y:visible;
        padding:10px 8px 72px 8px;
        scrollbar-color:#475569 #0f172a;
      }
      .calendar {
        min-width:1120px;
        display:grid;
        grid-template-columns:repeat(7, minmax(150px, 1fr));
        grid-auto-rows:minmax(238px, auto);
        gap:10px;
        align-items:stretch;
      }
      .dow {
        height:46px;
        min-height:46px;
        align-self:start;
        display:flex;
        align-items:center;
        justify-content:center;
        font-size:12px;
        font-weight:900;
        letter-spacing:.09em;
        color:#94a3b8;
        border-bottom:1px solid #334155;
      }
      .day-card, .blank {
        min-height:238px;
        border-radius:15px;
      }
      .blank {
        background:rgba(15,23,42,.35);
        border:1px dashed rgba(71,85,105,.28);
      }
      .day-card {
        position:relative;
        overflow:hidden;
        background:linear-gradient(145deg,#172033,#111827);
        border:1px solid #334155;
        box-shadow:0 8px 20px rgba(2,6,23,.20);
        padding:11px;
      }
      .day-card.weekend {
        background:linear-gradient(145deg,#1e293b,#111827);
      }
      .day-card.workday {
        background:linear-gradient(145deg,#123447,#0f2635);
        border-color:#0891b2;
      }
      .day-card.restday {
        background:linear-gradient(145deg,#151c29,#0b1220);
        border-color:#334155;
      }
      .day-card.changebreak {
        background:linear-gradient(145deg,#2b1d12,#17120e);
        border-color:#d97706;
      }
      .labor-tag {
        display:inline-block;
        margin-top:5px;
        padding:3px 7px;
        border-radius:999px;
        font-size:9px;
        font-weight:900;
        letter-spacing:.04em;
        color:white;
      }
      .labor-tag.work { background:#0e7490; }
      .labor-tag.rest { background:#475569; }
      .labor-tag.change { background:#b45309; }
      .day-card.today {
        border:2px solid #fb923c;
        box-shadow:0 0 0 2px rgba(251,146,60,.18), 0 12px 28px rgba(194,65,12,.28);
      }
      .day-card.full {
        border-color:#ef4444;
      }
      .day-card.medium {
        border-color:#facc15;
      }
      .day-card.light {
        border-color:#22c55e;
      }
      .day-top {
        display:flex;
        justify-content:space-between;
        align-items:flex-start;
        margin-bottom:8px;
      }
      .day-number {
        font-size:24px;
        font-weight:950;
        line-height:1;
        color:#f8fafc;
      }
      .today .day-number { color:#fdba74; }
      .count {
        min-width:27px;
        height:27px;
        padding:0 7px;
        border-radius:999px;
        display:flex;
        align-items:center;
        justify-content:center;
        font-size:12px;
        font-weight:900;
        color:#fff;
        background:#475569;
      }
      .count.c1 { background:#16a34a; }
      .count.c2 { background:#ca8a04; }
      .count.c3 { background:#dc2626; }
      .today-tag {
        display:inline-block;
        margin-top:5px;
        padding:3px 7px;
        border-radius:999px;
        background:#f97316;
        color:white;
        font-size:9px;
        font-weight:900;
        letter-spacing:.08em;
      }
      .entries {
        display:flex;
        flex-direction:column;
        gap:5px;
        margin-top:7px;
        min-height:118px;
      }
      .entry {
        display:grid;
        grid-template-columns:42px minmax(0,1fr);
        gap:6px;
        align-items:center;
        padding:5px 6px;
        border-radius:8px;
        background:rgba(15,23,42,.78);
        border:1px solid rgba(71,85,105,.45);
      }
      .code {
        border-radius:6px;
        text-align:center;
        padding:4px 3px;
        font-size:9px;
        font-weight:950;
        color:white;
      }
      .name {
        min-width:0;
        overflow:hidden;
        white-space:nowrap;
        text-overflow:ellipsis;
        font-size:10px;
        color:#f1f5f9;
        font-weight:700;
      }
      .empty-label {
        margin-top:22px;
        text-align:center;
        color:#64748b;
        font-size:11px;
      }
      .more {
        color:#94a3b8;
        font-size:10px;
        padding-left:4px;
        margin-top:2px;
      }
    </style>
    </head>
    <body>
      <div class="calendar-shell">
        <div class="calendar">
    """]

    for label in weekday_labels:
        html_parts.append(f'<div class="dow">{label}</div>')

    st.markdown(
        "<div style='display:flex;gap:10px;flex-wrap:wrap;margin:4px 0 10px 0'>"
        "<span style='background:#0e7490;color:white;padding:5px 10px;border-radius:999px;font-size:12px;font-weight:800'>■ TRABAJO</span>"
        "<span style='background:#334155;color:white;padding:5px 10px;border-radius:999px;font-size:12px;font-weight:800'>■ DESCANSO</span>"
        "<span style='background:#92400e;color:white;padding:5px 10px;border-radius:999px;font-size:12px;font-weight:800'>■ DESCANSO CAMBIO</span>"
        "</div>",
        unsafe_allow_html=True
    )

    for week in weeks:
        for idx, day in enumerate(week):
            if day == 0:
                html_parts.append('<div class="blank"></div>')
                continue

            registros = registros_por_dia.get(day, [])
            n = len(registros)
            is_today = (
                int(anio_c) == hoy.year and
                int(mes_c) == hoy.month and
                day == hoy.day
            )
            fecha_cal = dt.date(int(anio_c), int(mes_c), int(day))
            labor = info_calendario_laboral(fecha_cal)

            classes = ["day-card"]
            if labor["cambio"]:
                classes.append("changebreak")
            elif labor["trabaja"]:
                classes.append("workday")
            else:
                classes.append("restday")

            if idx >= 5:
                classes.append("weekend")
            if is_today:
                classes.append("today")
            if n >= 3:
                classes.append("full")
            elif n == 2:
                classes.append("medium")
            elif n == 1:
                classes.append("light")

            count_cls = "c3" if n >= 3 else "c2" if n == 2 else "c1" if n == 1 else ""
            today_tag = '<div class="today-tag">HOY</div>' if is_today else ""

            if labor["cambio"]:
                labor_tag = '<div class="labor-tag change">DESCANSO CAMBIO</div>'
            elif labor["trabaja"]:
                labor_tag = f'<div class="labor-tag work">TRABAJO · {labor["turno"].replace("TURNO ","")}</div>'
            else:
                labor_tag = f'<div class="labor-tag rest">DESCANSO · {labor["turno"].replace("TURNO ","")}</div>'

            entries_html = []
            # Mostrar hasta 4; normalmente el usuario solo puede llegar a 3,
            # pero el administrador sí puede rebasar el límite.
            for rec in registros[:4]:
                cod = codigo_tipo(rec.get("tipo",""))
                color = color_tipo(rec.get("tipo",""))
                nombre = html_lib.escape(str(rec.get("nombre","")))
                desc = html_lib.escape(etiqueta_tipo(rec.get("tipo","")))
                entries_html.append(
                    f'<div class="entry" title="{desc}">'
                    f'<div class="code" style="background:{color}">{html_lib.escape(cod)}</div>'
                    f'<div class="name">{nombre}</div></div>'
                )
            if len(registros) > 4:
                entries_html.append(f'<div class="more">+ {len(registros)-4} registro(s) más</div>')
            if not registros:
                entries_html.append('<div class="empty-label">Sin registros</div>')

            html_parts.append(
                f'<div class="{" ".join(classes)}">'
                f'<div class="day-top"><div><div class="day-number">{day}</div>{today_tag}{labor_tag}</div>'
                f'<div class="count {count_cls}">{n}</div></div>'
                f'<div class="entries">{"".join(entries_html)}</div>'
                f'</div>'
            )

    html_parts.append("""
        </div>
        <div style="height:48px;width:100%"></div>
      </div>
    </body>
    </html>
    """)

    # Altura robusta del iframe:
    #  - 46 px encabezados
    #  - ~248 px por semana (tarjeta + separación)
    #  - margen inferior amplio para evitar que Streamlit recorte la última fila.
    calendar_height = 210 + (len(weeks) * 258)

    components.html(
        "".join(html_parts),
        height=calendar_height,
        scrolling=False
    )

if st.session_state.is_admin:
    with tab_matrix:
        st.markdown("""
        <div class="matrix-hero">
          <div class="matrix-title">⚡ Centro de Control de Incidencias</div>
          <div class="matrix-sub">Haz clic en empleado + día para editar. En vista Amplia los días conservan un tamaño cómodo y se navega horizontalmente; Compacta muestra más columnas.</div>
        </div>
        """, unsafe_allow_html=True)

        empleados_df = load_empleados_df()
        agenda = load_agenda()
        req_df = load_requerimientos()
        req_map = {
            canonical_team(r["equipo"]).strip().lower(): {
                "let": int(r["let_requeridos"]),
                "met": int(r["met_requeridos"]),
            }
            for _, r in req_df.iterrows()
            if is_operational_team(r["equipo"])
        } if not req_df.empty else {}
        hoy = dt.date.today()

        st.markdown("##### Filtros de la matriz")
        top1, top2, top3, top4 = st.columns([1,1,2.2,1])
        anio_i = top1.number_input("Año", value=hoy.year, min_value=hoy.year-1, max_value=hoy.year+3, key="i_anio")
        mes_i = top2.selectbox("Mes", range(1,13), index=hoy.month-1, format_func=lambda x: MESES[x-1], key="i_mes")
        busqueda = top3.text_input("🔍 Buscar colaborador, número, equipo o función", key="i_buscar")
        densidad = top4.selectbox("Vista", ["Amplia", "Compacta"], index=0, key="i_densidad")

        if densidad == "Amplia":
            # Priorizamos legibilidad. No intentamos meter los 31 días a la fuerza:
            # la matriz usa desplazamiento horizontal.
            day_width = 104
            day_min = 98
            day_max = 112
            row_height = 52
            header_height = 92
            grid_height = 880
            colaborador_width = 420
            equipo_width = 0
            funcion_width = 112
        else:
            day_width = 78
            day_min = 74
            day_max = 86
            row_height = 44
            header_height = 82
            grid_height = 800
            colaborador_width = 370
            equipo_width = 0
            funcion_width = 100

        ultimo = calendar.monthrange(int(anio_i), int(mes_i))[1]
        agenda_m = agenda[
            (agenda["fecha"].dt.year == int(anio_i)) &
            (agenda["fecha"].dt.month == int(mes_i))
        ].copy() if not agenda.empty else agenda.copy()

        if not agenda_m.empty:
            agenda_m["codigo"] = agenda_m["tipo"].apply(codigo_tipo)
            agenda_m["dia"] = agenda_m["fecha"].dt.day

        # KPIs de plantilla / función
        if "funcion" not in empleados_df.columns:
            empleados_df["funcion"] = ""
        empleados_df["funcion"] = empleados_df["funcion"].astype(str).str.strip().str.upper()
        total_personas = len(empleados_df)
        total_let = int((empleados_df["funcion"] == "LET").sum())
        total_met = int((empleados_df["funcion"] == "MET").sum())
        total_pool = int((empleados_df["funcion"] == "POOL").sum())
        sin_funcion = int((~empleados_df["funcion"].isin(FUNCIONES)).sum())

        req_let_total = sum(v.get("let",0) for v in req_map.values())
        req_met_total = sum(v.get("met",0) for v in req_map.values())

        # KPIs mensuales
        total_mes = len(agenda_m)
        vac_mes = int((agenda_m["codigo"] == "VAC").sum()) if not agenda_m.empty else 0
        faltas_mes = int(agenda_m["codigo"].isin(["FI","FJ"]).sum()) if not agenda_m.empty else 0
        permisos_mes = int(agenda_m["codigo"].isin(["PSG","PPSG","DEF","PAT"]).sum()) if not agenda_m.empty else 0
        incap_mes = int(agenda_m["codigo"].isin(["INC","SM","RM","EM"]).sum()) if not agenda_m.empty else 0

        render_kpi_panel("Plantilla", [
            ("👥 Personas", total_personas),
            ("🔷 LET", total_let),
            ("🟣 MET", total_met),
            ("🟠 POOL", total_pool),
            ("⚪ Sin función", sin_funcion),
        ])

        st.caption("💡 Clic en empleado + día para editar · HOY resaltado · columnas izquierdas congeladas.")

        periodos_mes = periodos_laborales_mes(int(anio_i), int(mes_i))
        chips_turno = []
        for ini_p, fin_p, turno_p in periodos_mes:
            if turno_p == "DESCANSO CAMBIO":
                bg = "#92400e"
            elif turno_p == "SIN CALENDARIO":
                bg = "#475569"
            else:
                bg = "#0e7490"
            rango_txt = f"{ini_p}" if ini_p == fin_p else f"{ini_p}–{fin_p}"
            chips_turno.append(
                f"<span style='display:inline-block;background:{bg};color:white;"
                f"padding:5px 9px;border-radius:999px;font-size:11px;font-weight:800'>"
                f"{rango_txt}: {turno_p}</span>"
            )
        st.markdown(
            "<div style='display:flex;gap:7px;flex-wrap:wrap;margin:2px 0 8px 0'>"
            + "".join(chips_turno)
            + "</div>"
            "<div style='display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px'>"
            "<span style='background:#0e7490;color:white;padding:4px 9px;border-radius:999px;font-size:11px;font-weight:800'>DÍA DE TRABAJO</span>"
            "<span style='background:#334155;color:white;padding:4px 9px;border-radius:999px;font-size:11px;font-weight:800'>DESCANSO</span>"
            "<span style='background:#92400e;color:white;padding:4px 9px;border-radius:999px;font-size:11px;font-weight:800'>CAMBIO · 5 DÍAS</span>"
            "</div>",
            unsafe_allow_html=True
        )

        # Filtro
        edf = empleados_df.copy()
        if busqueda:
            q = busqueda.lower().strip()
            edf = edf[
                edf["nombre"].str.lower().str.contains(q, na=False) |
                edf["numero"].str.lower().str.contains(q, na=False) |
                edf["equipo"].str.lower().str.contains(q, na=False) |
                edf["funcion"].astype(str).str.lower().str.contains(q, na=False)
            ].copy()

        if "funcion" not in edf.columns:
            edf["funcion"] = ""
        edf["funcion"] = edf["funcion"].astype(str).str.strip().str.upper()
        edf["equipo_canon"] = edf["equipo"].apply(canonical_team)

        # Matriz exclusivamente en el orden operativo solicitado.
        # Alias como "ESPARTANS" o "UNDER ZIDE B" se agrupan en su nombre oficial.
        edf = edf[edf["equipo_canon"].str.lower().isin(TEAM_RANK.keys())].copy()
        edf["_team_rank"] = edf["equipo_canon"].str.lower().map(TEAM_RANK)
        edf = edf.sort_values(["_team_rank","nombre"], kind="stable").reset_index(drop=True)

        # Valor actual por empleado/día.
        # Si por alguna razón hay más de uno, mostramos el último registro.
        current = {}
        if not agenda_m.empty:
            for _, r in agenda_m.sort_values("fecha").iterrows():
                current[(str(r["numero"]).strip(), int(r["dia"]))] = codigo_tipo(r["tipo"])

        # Construir matriz incluyendo filas separadoras de equipo
        rows = []
        teams_in_order = TEAM_ORDER.copy()

        for team in teams_in_order:
            grp = edf[edf["equipo_canon"].astype(str).str.lower().str.strip() == team.lower().strip()]
            if grp.empty:
                continue

            # El LET funciona como encabezado visual del equipo.
            # Los LET permanecen también en su fila normal, tal como pidió el usuario.
            lets_team = grp[grp["funcion"].astype(str).str.upper().str.strip() == "LET"]
            if not lets_team.empty:
                let_names = lets_team["nombre"].astype(str).tolist()
                if len(let_names) == 1:
                    header_team = f"{let_names[0]} (LET) · {team.upper()}"
                else:
                    header_team = f"{let_names[0]} (LET) +{len(let_names)-1} LET · {team.upper()}"
            else:
                header_team = f"SIN LET · {team.upper()}"

            group_row = {
                "es_grupo": True,
                "Equipo": team.upper(),
                "Función": "",
                "Colaborador": header_team,
                "numero": "",
                "nombre_real": "",
                "equipo_real": team,
                "funcion_real": "",
            }
            for d in range(1, ultimo+1):
                group_row[str(d)] = ""
            rows.append(group_row)

            for _, er in grp.iterrows():
                num = str(er["numero"]).strip()
                funcion = str(er.get("funcion","")).strip().upper()
                row = {
                    "es_grupo": False,
                    "Equipo": "",
                    "Función": funcion or "—",
                    "Colaborador": f"{num}   {er['nombre']}",
                    "numero": num,
                    "nombre_real": str(er["nombre"]),
                    "equipo_real": canonical_team(er["equipo"]),
                    "funcion_real": funcion,
                }
                for d in range(1, ultimo+1):
                    row[str(d)] = current.get((num, d), "")
                rows.append(row)

        matrix_df = pd.DataFrame(rows)

        incidence_options = [""] + list(INCIDENCIAS.keys())
        weekday_es = ["LUN","MAR","MIÉ","JUE","VIE","SÁB","DOM"]

        def estilo_dia_js(info_dia):
            fondo = info_dia["cell_color"]
            borde = "#0891b2" if info_dia["trabaja"] else ("#d97706" if info_dia["cambio"] else "#334155")
            return JsCode(f"""
            function(params) {{
                if (params.data && params.data.es_grupo) {{
                    return {{
                        backgroundColor:'#cbd5e1',
                        color:'#0f172a',
                        fontWeight:'900',
                        borderColor:'#cbd5e1',
                        fontSize:'12px'
                    }};
                }}

                const colors = {{
                    'VAC':'#10b981','PSG':'#fbbf24','PPSG':'#f59e0b',
                    'FI':'#ef4444','FJ':'#eab308','SAN':'#dc2626',
                    'RET':'#2563eb','DEF':'#64748b','PAT':'#0ea5e9',
                    'INC':'#a855f7','SM':'#ec4899','RM':'#14b8a6',
                    'EM':'#d946ef','BJ':'#6b7280','TE':'#60a5fa',
                    'PT':'#f97316','TRB':'#15803d'
                }};

                const v = params.value || '';
                if (!v) {{
                    return {{
                        backgroundColor:'{fondo}',
                        color:'#94a3b8',
                        textAlign:'center',
                        borderColor:'{borde}'
                    }};
                }}

                return {{
                    backgroundColor: colors[v] || '#475569',
                    color:'#ffffff',
                    fontWeight:'900',
                    textAlign:'center',
                    borderRadius:'7px',
                    border:'2px solid rgba(255,255,255,.16)'
                }};
            }}
            """)


        editable_day = JsCode("""
        function(params) {
            return !(params.data && params.data.es_grupo);
        }
        """)

        row_style = JsCode("""
        function(params) {
            if (params.data && params.data.es_grupo) {
                return {
                    backgroundColor:'#cbd5e1',
                    color:'#0f172a',
                    fontWeight:'900',
                    borderTop:'5px solid #0f172a',
                    borderBottom:'2px solid #94a3b8'
                };
            }
            return {
                backgroundColor:'#172033',
                color:'#e5e7eb'
            };
        }
        """)

        funcion_style = JsCode("""
        function(params) {
            if (params.data && params.data.es_grupo) {
                return {backgroundColor:'#cbd5e1', color:'#0f172a', fontWeight:'900'};
            }
            const colors = {'LET':'#06b6d4','MET':'#8b5cf6','POOL':'#f59e0b','—':'#475569'};
            const v = params.value || '—';
            return {
                backgroundColor: colors[v] || '#475569',
                color:'#fff', fontWeight:'900', textAlign:'center',
                borderRadius:'8px'
            };
        }
        """)

        # Totales fijos al pie: responden al filtro actual.
        filtered_nums = set(edf["numero"].astype(str).str.strip().tolist())
        agenda_view = agenda_m[agenda_m["numero"].astype(str).str.strip().isin(filtered_nums)].copy() if not agenda_m.empty else agenda_m.copy()
        pinned_rows = []
        labels = ["Σ Incidencias", "VAC", "Faltas", "Permisos", "INC/Médico", "LET libres", "MET libres", "POOL libres"]
        for label in labels:
            prow = {"es_grupo": False, "Equipo":"", "Función":"", "Colaborador":label, "numero":"", "nombre_real":"", "equipo_real":"", "funcion_real":""}
            for day in range(1, ultimo+1):
                dd = agenda_view[agenda_view["dia"] == day] if not agenda_view.empty else agenda_view
                codes = dd["codigo"] if not dd.empty else pd.Series(dtype=str)
                if label == "Σ Incidencias": value = len(dd)
                elif label == "VAC": value = int((codes == "VAC").sum())
                elif label == "Faltas": value = int(codes.isin(["FI","FJ"]).sum())
                elif label == "Permisos": value = int(codes.isin(["PSG","PPSG","DEF","PAT"]).sum())
                elif label == "INC/Médico": value = int(codes.isin(["INC","SM","RM","EM"]).sum())
                else:
                    unavailable_nums = set(
                        dd[dd["codigo"].isin(NO_DISPONIBLE)]["numero"].astype(str).str.strip().tolist()
                    ) if not dd.empty else set()

                    # Cobertura CHASIS 1 usando la misma lógica del panel:
                    # MET base -> POOL cubre primera ausencia MET -> LET segunda.
                    let_free_total = 0
                    pool_available_total = 0
                    met_surplus_total = 0

                    for team_f in TEAM_ORDER:
                        key_team = team_f.strip().lower()
                        tdf = edf[
                            edf["equipo_canon"].astype(str).str.strip().str.lower() == key_team
                        ]
                        if tdf.empty:
                            continue

                        req_t = req_map.get(key_team, {"let":0, "met":0})
                        req_m = int(req_t.get("met", 0))

                        cov = calcular_cobertura_equipo(
                            tdf,
                            unavailable_nums,
                            req_met=req_m
                        )

                        let_free_total += cov["let_libre"]
                        pool_available_total += cov["pool_libre"]

                        # Solo mostramos como MET libres a MET reales por encima
                        # del requerimiento, si existieran.
                        nums_t = tdf["numero"].astype(str).str.strip()
                        met_disponibles = int(
                            ((tdf["funcion"] == "MET") &
                             ~nums_t.isin(unavailable_nums)).sum()
                        )
                        met_surplus_total += max(met_disponibles - req_m, 0)

                    if label == "LET libres":
                        value = let_free_total
                    elif label == "MET libres":
                        value = met_surplus_total
                    else:
                        value = pool_available_total
                prow[str(day)] = value
            pinned_rows.append(prow)

        gb = GridOptionsBuilder.from_dataframe(matrix_df)
        gb.configure_default_column(
            sortable=False,
            filter=False,
            resizable=True,
            suppressMenu=True,
        )
        gb.configure_column("es_grupo", hide=True)
        gb.configure_column("numero", hide=True)
        gb.configure_column("nombre_real", hide=True)
        gb.configure_column("equipo_real", hide=True)
        gb.configure_column("funcion_real", hide=True)
        # Ahorramos una columna completa: Equipo queda oculto.
        # El equipo se identifica en la fila encabezado mediante el LET.
        gb.configure_column("Equipo", hide=True)
        gb.configure_column("Función", pinned="left", width=funcion_width, minWidth=92, maxWidth=120, editable=False, cellStyle=funcion_style)
        gb.configure_column("Colaborador", pinned="left", width=colaborador_width + 80, minWidth=390, maxWidth=560, editable=False)

        for d in range(1, ultimo+1):
            fecha_d = dt.date(int(anio_i), int(mes_i), d)
            weekday = weekday_es[fecha_d.weekday()]
            labor_d = info_calendario_laboral(fecha_d)
            is_today = (int(anio_i) == hoy.year and int(mes_i) == hoy.month and d == hoy.day)

            if is_today:
                header_class = "today-header"
                cell_class = "today-col"
            elif labor_d["cambio"]:
                header_class = "change-header"
                cell_class = "change-col"
            elif labor_d["trabaja"]:
                header_class = "work-header"
                cell_class = "work-col"
            else:
                header_class = "rest-header"
                cell_class = "rest-col"

            gb.configure_column(
                str(d),
                header_name=(f"🔥 {d}\n{weekday}" if is_today else f"{d}\n{weekday}"),
                headerClass=header_class,
                cellClass=cell_class,
                editable=editable_day,
                cellEditor="agSelectCellEditor",
                cellEditorParams={"values": incidence_options},
                cellStyle=estilo_dia_js(labor_d),
                width=day_width,
                minWidth=day_min,
                maxWidth=day_max,
                wrapHeaderText=True,
                autoHeaderHeight=False,
            )

        group_height_js = JsCode(f"""
        function(params) {{
            if (params.data && params.data.es_grupo) return 36;
            return {row_height};
        }}
        """)

        gb.configure_grid_options(
            singleClickEdit=True,
            stopEditingWhenCellsLoseFocus=True,
            rowHeight=row_height,
            headerHeight=header_height,
            animateRows=True,
            suppressRowClickSelection=True,
            ensureDomOrder=True,
            getRowStyle=row_style,
            getRowHeight=group_height_js,
            pinnedBottomRowData=pinned_rows,
        )

        custom_css = {
            ".ag-root-wrapper": {
                "width": "100% !important",
                "border": "1px solid #334155 !important",
                "border-radius": "16px !important",
                "overflow": "hidden !important",
                "box-shadow": "0 18px 45px rgba(2,6,23,.32) !important",
                "background": "#111827 !important",
                "font-size": "13px !important",
            },
            ".ag-root-wrapper-body": {
                "background": "#111827 !important",
            },
            ".ag-body-viewport": {
                "background": "#111827 !important",
            },
            ".ag-center-cols-viewport": {
                "background": "#111827 !important",
            },
            ".ag-center-cols-container": {
                "background": "#111827 !important",
            },
            ".ag-body-horizontal-scroll": {
                "background": "#0b1220 !important",
                "min-height": "16px !important",
            },
            ".ag-header": {
                "background": "linear-gradient(180deg,#0b1220,#111c31) !important",
                "border-bottom": "2px solid #334155 !important",
            },
            ".ag-header-cell": {
                "color": "#f8fafc !important",
                "font-weight": "800 !important",
                "border-right": "1px solid #334155 !important",
            },
            ".ag-header-cell-label": {
                "height": "100% !important",
                "display": "flex !important",
                "align-items": "center !important",
                "justify-content": "center !important",
                "overflow": "visible !important",
                "padding-top": "6px !important",
                "padding-bottom": "6px !important",
            },
            ".ag-header-cell-text": {
                "white-space": "pre-line !important",
                "overflow": "visible !important",
                "text-overflow": "clip !important",
                "line-height": "1.35 !important",
                "text-align": "center !important",
                "font-size": "13px !important",
                "font-weight": "900 !important",
            },
            ".ag-pinned-left-header .ag-header-cell-text": {
                "white-space": "normal !important",
                "font-size": "13px !important",
            },
            ".ag-pinned-left-cols-container .ag-cell": {
                "display": "flex !important",
                "align-items": "center !important",
            },
            ".ag-center-cols-container .ag-cell": {
                "display": "flex !important",
                "align-items": "center !important",
                "justify-content": "center !important",
            },
            ".ag-cell": {
                "border-right": "1px solid #334155 !important",
                "border-bottom": "1px solid #334155 !important",
                "overflow": "visible !important",
            },
            ".ag-cell-focus": {
                "border": "2px solid #38bdf8 !important",
                "box-shadow": "inset 0 0 0 1px #e0f2fe !important",
            },
            ".ag-row-hover": {
                "background-color": "#22304a !important",
            },
            ".today-header": {
                "background": "linear-gradient(180deg,#f97316,#c2410c) !important",
                "color": "white !important",
                "box-shadow": "inset 0 -3px 0 #fde68a !important",
            },
            ".work-header": {
                "background": "linear-gradient(180deg,#0e7490,#155e75) !important",
                "color": "white !important",
                "box-shadow": "inset 0 -3px 0 #22d3ee !important",
            },
            ".rest-header": {
                "background": "linear-gradient(180deg,#1e293b,#111827) !important",
                "color": "#94a3b8 !important",
            },
            ".change-header": {
                "background": "linear-gradient(180deg,#92400e,#78350f) !important",
                "color": "#fff7ed !important",
                "box-shadow": "inset 0 -3px 0 #f59e0b !important",
            },
            ".today-col": {
                "border-left": "2px solid #fb923c !important",
                "border-right": "2px solid #fb923c !important",
            },
            ".ag-floating-bottom": {
                "border-top": "3px solid #38bdf8 !important",
                "background": "#0b1220 !important",
            },
            ".ag-floating-bottom .ag-cell": {
                "background": "#0b1220 !important",
                "color": "#e0f2fe !important",
                "font-weight": "800 !important",
                "font-size": "11px !important",
            },
        }

        response = AgGrid(
            matrix_df,
            gridOptions=gb.build(),
            update_mode=GridUpdateMode.VALUE_CHANGED,
            data_return_mode=DataReturnMode.AS_INPUT,
            fit_columns_on_grid_load=False,
            allow_unsafe_jscode=True,
            theme="alpine",
            custom_css=custom_css,
            height=grid_height,
            key=f"inc_grid_{int(anio_i)}_{int(mes_i)}_{busqueda}_{densidad}",
        )

        edited = pd.DataFrame(response["data"]) if response and response.get("data") is not None else matrix_df.copy()

        # Detectar una edición y guardarla automáticamente
        if not edited.empty:
            original_by_num = {}
            for _, r in matrix_df[matrix_df["es_grupo"] == False].iterrows():
                original_by_num[str(r["numero"])] = r

            change = None
            for _, r in edited[edited["es_grupo"] == False].iterrows():
                num = str(r["numero"]).strip()
                old = original_by_num.get(num)
                if old is None:
                    continue
                for d in range(1, ultimo+1):
                    col = str(d)
                    old_val = str(old.get(col, "") or "").strip()
                    new_val = str(r.get(col, "") or "").strip()
                    if old_val != new_val:
                        change = (r, d, old_val, new_val)
                        break
                if change:
                    break

            if change:
                r, d, old_val, new_val = change
                fecha_edit = dt.date(int(anio_i), int(mes_i), int(d))
                try:
                    # Usar la fila ya cargada en memoria; así NO se vuelve a leer
                    # toda la hoja de Google en cada click de la matriz.
                    existing_row = None
                    if not agenda_m.empty and "_sheet_row" in agenda_m.columns:
                        match_existing = agenda_m[
                            (agenda_m["numero"].astype(str).str.strip() == str(r["numero"]).strip()) &
                            (agenda_m["dia"] == int(d))
                        ].copy()
                        if not match_existing.empty:
                            match_existing = match_existing.sort_values("_sheet_row")
                            existing_row = int(match_existing.iloc[-1]["_sheet_row"])

                    action = set_admin_incidence(
                        numero=str(r["numero"]).strip(),
                        nombre=str(r["nombre_real"]).strip(),
                        equipo=str(r["equipo_real"]).strip(),
                        fecha=fecha_edit.isoformat(),
                        tipo=new_val,
                        existing_row=existing_row,
                    )
                    clear_agenda_cache()
                    if new_val:
                        st.toast(f"✅ {new_val} guardado: {r['nombre_real']} · {fecha_edit.strftime('%d/%m/%Y')}")
                    else:
                        st.toast(f"🗑️ Incidencia eliminada: {r['nombre_real']} · {fecha_edit.strftime('%d/%m/%Y')}")
                    st.rerun()
                except Exception as e:
                    msg = str(e)
                    if "429" in msg or "Quota exceeded" in msg or "Read requests" in msg:
                        st.warning(
                            "Google Sheets alcanzó temporalmente su límite de lecturas. "
                            "Espera aproximadamente 60 segundos y vuelve a intentar. "
                            "Esta versión ya reduce las lecturas por cada cambio."
                        )
                    else:
                        st.error(f"No se pudo guardar el cambio: {e}")

        # Leyenda
        legend_html = "".join(
            f"<span style='display:inline-block;background:{color};color:white;padding:6px 11px;"
            f"border-radius:16px;margin:3px;font-size:11px;font-weight:800'>{cod} — {html_lib.escape(desc)}</span>"
            for cod,(desc,color) in INCIDENCIAS.items()
        )
        st.markdown(legend_html, unsafe_allow_html=True)

        # Panel operativo compacto del día seleccionado
        st.markdown("---")
        st.markdown("### 🎯 Control operativo del día")
        st.caption(
            "CHASIS 1 · Los MET cubren las estaciones. POOL y LET son personal extra: "
            "ante una ausencia MET, primero cubre POOL; ante una segunda ausencia MET, cubre LET. "
            "Solo si faltan más MET se marca una necesidad."
        )

        dia_res = st.selectbox(
            "Día seleccionado",
            range(1, ultimo+1),
            index=min(hoy.day, ultimo)-1,
            format_func=lambda d: f"{d:02d} de {MESES[int(mes_i)-1]}",
            key="res_dia_select"
        )

        fecha_operativa = dt.date(int(anio_i), int(mes_i), int(dia_res))
        labor_operativa = info_calendario_laboral(fecha_operativa)
        estado_laboral = "TRABAJO" if labor_operativa["trabaja"] else "DESCANSO"
        if labor_operativa["cambio"]:
            estado_laboral = "DESCANSO CAMBIO"
        st.markdown(
            f"<div style='margin:-2px 0 10px 0;padding:8px 11px;border-radius:10px;"
            f"background:{labor_operativa['color']};color:white;font-size:12px;font-weight:900'>"
            f"{fecha_operativa.strftime('%d/%m/%Y')} · {labor_operativa['turno']} · {estado_laboral}"
            f"</div>",
            unsafe_allow_html=True
        )

        ddf = agenda_m[agenda_m["dia"] == int(dia_res)].copy() if not agenda_m.empty else agenda_m.copy()
        codes_day = ddf["codigo"] if not ddf.empty else pd.Series(dtype=str)

        # Solo estas incidencias afectan cobertura.
        unavailable_day = ddf[ddf["codigo"].isin(NO_DISPONIBLE)].copy() if not ddf.empty else ddf.copy()
        unavailable = set(
            unavailable_day["numero"].astype(str).str.strip().tolist()
        ) if not unavailable_day.empty else set()

        base_staff = empleados_df.copy()
        base_staff["funcion"] = base_staff["funcion"].astype(str).str.strip().str.upper()
        base_staff["equipo_canon"] = base_staff["equipo"].apply(canonical_team)
        base_staff = base_staff[
            base_staff["equipo_canon"].astype(str).str.lower().isin(TEAM_RANK.keys())
        ].copy()

        coverage_rows = []
        lets_libres_total = 0

        # Denominador esperado para "LET libres X de Y".
        lets_requeridos_total = sum(
            int(req_map.get(team.lower(), {}).get("let", 0))
            for team in TEAM_ORDER
        )
        if lets_requeridos_total <= 0:
            lets_requeridos_total = int((base_staff["funcion"] == "LET").sum())

        for team in TEAM_ORDER:
            team_staff = base_staff[
                base_staff["equipo_canon"].astype(str).str.strip().str.lower() == team.lower()
            ]
            if team_staff.empty:
                continue

            nums_team = team_staff["numero"].astype(str).str.strip()
            team_unavailable = set(nums_team[nums_team.isin(unavailable)].tolist())

            req = req_map.get(team.lower(), {"let":0, "met":0})
            req_met = int(req.get("met", 0))

            cov = calcular_cobertura_equipo(
                team_staff,
                unavailable,
                req_met=req_met
            )

            lets_libres_total += cov["let_libre"]

            coverage_rows.append({
                "Equipo": team,
                "Incidencias": cov["incidencias"],
                "Ausencias MET": cov["ausencias_met"],
                "POOL cubre": cov["pool_cubre"],
                "LET cubre": cov["let_cubre"],
                "LET libre": cov["let_libre"],
                "POOL libre": cov["pool_libre"],
                "Estado": cov["estado"],
            })

        # Resumen exactamente orientado al día seleccionado.
        # Permiso se separa de Paternidad y Defunción.
        known_codes = {
            "VAC","FI","FJ","PSG","PPSG","SAN","RET","INC","PAT",
            "SM","RM","DEF","EM","BJ","TE","PT","TRB"
        }
        otros_count = int((~codes_day.isin(known_codes)).sum()) if not codes_day.empty else 0

        resumen_dia = [
            ("ÁREA", "CHASIS 1"),
            ("LETS LIBRES", f"{lets_libres_total} de {lets_requeridos_total}"),
            ("VACACIONES", int((codes_day == "VAC").sum())),
            ("FALTAS", int(codes_day.isin(["FI","FJ"]).sum())),
            ("PERMISO", int(codes_day.isin(["PSG","PPSG"]).sum())),
            ("SANCIONES", int((codes_day == "SAN").sum())),
            ("RETARDOS", int((codes_day == "RET").sum())),
            ("INCAPACIDAD", int((codes_day == "INC").sum())),
            ("PATERNIDAD", int((codes_day == "PAT").sum())),
            ("SERVICIO MÉDICO", int((codes_day == "SM").sum())),
            ("RESTRICCIÓN MÉDICA", int((codes_day == "RM").sum())),
            ("DEFUNCIÓN", int((codes_day == "DEF").sum())),
            ("EMBARAZADA", int((codes_day == "EM").sum())),
            ("BAJA", int((codes_day == "BJ").sum())),
            ("PARO TÉCNICO", int((codes_day == "PT").sum())),
            ("SOPORTE TE", int((codes_day == "TE").sum())),
            ("OTROS", otros_count),
        ]

        # Ocultar incidencias con valor 0 o vacío.
        # ÁREA y LETS LIBRES siempre permanecen visibles.
        resumen_dia = [
            (label, value)
            for label, value in resumen_dia
            if label in ("ÁREA", "LETS LIBRES")
            or (value not in (0, "", None))
        ]

        col_res, col_cov = st.columns([0.72, 2.28], gap="large")

        with col_res:
            st.markdown("#### 📋 Resumen del día — CHASIS 1")
            items_html = "".join(
                f"<div style='display:flex;justify-content:space-between;gap:14px;"
                f"padding:7px 10px;border-bottom:1px solid #26364f;'>"
                f"<span style='color:#cbd5e1;font-size:12px;font-weight:800'>{html_lib.escape(str(label))}</span>"
                f"<span style='color:#fff;font-size:15px;font-weight:950;white-space:nowrap'>{html_lib.escape(str(value))}</span>"
                f"</div>"
                for label, value in resumen_dia
            )
            st.markdown(
                f"<div style='border:1px solid #334155;border-radius:14px;overflow:hidden;"
                f"background:#111827'>{items_html}</div>",
                unsafe_allow_html=True
            )

        with col_cov:
            st.markdown("#### ⚙️ Cobertura por equipo")
            if not req_map:
                st.warning("Configura requerimientos en Administración → Requerimientos por equipo.")

            if coverage_rows:
                coverage_df = pd.DataFrame(coverage_rows)

                # El orden queda fijo exactamente como fue solicitado.
                coverage_df["__orden"] = coverage_df["Equipo"].str.lower().map(TEAM_RANK)
                coverage_df = coverage_df.sort_values("__orden", kind="stable").drop(columns="__orden")

                st.dataframe(
                    coverage_df[
                        ["Equipo","Incidencias","Ausencias MET","POOL cubre","LET cubre","LET libre","POOL libre","Estado"]
                    ],
                    hide_index=True,
                    use_container_width=True,
                    height=min(390, 46 + len(coverage_df) * 36)
                )
            else:
                st.info("No hay equipos para mostrar.")

        with st.expander("👤 Ver personas con incidencia este día", expanded=False):
            if ddf.empty:
                st.info("Sin incidencias ese día.")
            else:
                detalle = ddf.copy()
                detalle["equipo_canon"] = detalle["equipo"].apply(canonical_team)
                detalle["__orden"] = detalle["equipo_canon"].str.lower().map(TEAM_RANK)
                detalle = detalle.sort_values(["__orden","nombre"], kind="stable")
                st.dataframe(
                    detalle[["numero","nombre","equipo_canon","codigo","tipo"]].rename(
                        columns={"equipo_canon":"equipo"}
                    ),
                    hide_index=True,
                    use_container_width=True
                )

    with tab_rep:
        st.header("Resumen mensual por equipos")
        agenda = load_agenda(); hoy = dt.date.today()
        r1, r2 = st.columns(2)
        ar = r1.number_input("Año", value=hoy.year, min_value=hoy.year-2, max_value=hoy.year+3, key="r_anio")
        mr = r2.selectbox("Mes", range(1,13), index=hoy.month-1, format_func=lambda x: MESES[x-1], key="r_mes")
        rm = agenda[(agenda["fecha"].dt.year==int(ar)) & (agenda["fecha"].dt.month==int(mr))].copy() if not agenda.empty else agenda.copy()
        if rm.empty:
            st.info("Sin datos para el mes.")
        else:
            rm["codigo"] = rm["tipo"].apply(codigo_tipo)
            pivot = pd.crosstab(rm["equipo"], rm["codigo"]); pivot["Total"] = pivot.sum(axis=1); pivot = pivot.sort_values("Total", ascending=False)
            st.dataframe(pivot, use_container_width=True); st.bar_chart(pivot["Total"])
            excel = BytesIO()
            with pd.ExcelWriter(excel, engine="xlsxwriter") as writer:
                pivot.to_excel(writer, sheet_name="Resumen_Equipos"); rm.to_excel(writer, sheet_name="Detalle", index=False)
            st.download_button("⬇️ Descargar reporte Excel", data=excel.getvalue(), file_name=f"reporte_{int(ar)}_{int(mr):02d}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    with tab_admin:
        st.header("Administración")
        sec = st.radio("Sección", ["Empleados", "Requerimientos por equipo", "Eliminar incidencias"], horizontal=True)
        if sec == "Empleados":
            st.subheader("Funciones del personal: LET / MET / POOL")
            roles_base = load_empleados_df().copy()
            if "funcion" not in roles_base.columns:
                roles_base["funcion"] = ""
            roles_edit = st.data_editor(
                roles_base[["numero","nombre","equipo","funcion"]],
                use_container_width=True,
                hide_index=True,
                disabled=["numero","nombre","equipo"],
                column_config={
                    "funcion": st.column_config.SelectboxColumn(
                        "Función",
                        help="Asigna LET, MET o POOL",
                        options=["LET","MET","POOL"],
                        required=False,
                    )
                },
                key="roles_editor"
            )
            if st.button("💾 Guardar funciones", key="save_roles", type="primary"):
                roles_edit["funcion"] = roles_edit["funcion"].fillna("").astype(str).str.upper().str.strip()
                replace_empleados_df(roles_edit[["numero","nombre","equipo","funcion"]])
                clear_empleados_cache(); st.success("Funciones actualizadas"); st.rerun()

            st.markdown("---")
            st.subheader("Agregar más personas")
            with st.form("nuevo_empleado"):
                c1,c2,c3,c4 = st.columns([1,2,1,1])
                nnum = c1.text_input("Número de empleado")
                nnom = c2.text_input("Nombre completo")
                neq = c3.text_input("Equipo")
                nfun = c4.selectbox("Función", ["", "LET", "MET", "POOL"])
                ok = st.form_submit_button("Agregar empleado")
            if ok:
                if not nnum or not nnom or not neq: st.error("Completa número, nombre y equipo.")
                else:
                    append_empleados_rows(pd.DataFrame([{"numero":nnum.strip(),"nombre":nnom.strip(),"equipo":neq.strip(),"funcion":nfun.strip()}]))
                    clear_empleados_cache(); st.success("Empleado agregado"); st.rerun()
            st.subheader("Importar empleados desde Excel/CSV")
            up = st.file_uploader("Archivo con columnas numero, nombre, equipo", type=["csv","xlsx"], key="emp_up")
            if up is not None:
                dfup = pd.read_csv(up) if up.name.lower().endswith(".csv") else pd.read_excel(up)
                cols = {c.lower().strip():c for c in dfup.columns}
                if all(x in cols for x in ["numero","nombre","equipo"]):
                    funcion_col = cols.get("funcion")
                    norm = pd.DataFrame({
                        "numero":dfup[cols["numero"]].astype(str).str.strip(),
                        "nombre":dfup[cols["nombre"]].astype(str).str.strip(),
                        "equipo":dfup[cols["equipo"]].astype(str).str.strip(),
                        "funcion":(dfup[funcion_col].astype(str).str.strip().str.upper() if funcion_col else "")
                    })
                    st.dataframe(norm.head(20), use_container_width=True)
                    if st.button("Reemplazar lista completa", key="replace_emp"):
                        replace_empleados_df(norm); clear_empleados_cache(); st.success("Lista actualizada"); st.rerun()
                else: st.error("El archivo debe tener: numero, nombre, equipo. La columna funcion es opcional.")
        elif sec == "Requerimientos por equipo":
            st.subheader("🎯 Requerimiento mínimo por equipo")
            st.caption("Define cuántos LET y MET necesita cada equipo para operar. La app calculará faltantes y MET sobrantes que pueden pasar a POOL.")

            req_actual = load_requerimientos().copy()
            emp_actual = load_empleados_df().copy()
            equipos_req = TEAM_ORDER.copy()
            actual_map = {
                canonical_team(r["equipo"]).strip().lower(): (int(r["let_requeridos"]), int(r["met_requeridos"]))
                for _, r in req_actual.iterrows()
                if is_operational_team(r["equipo"])
            } if not req_actual.empty else {}
            req_base = pd.DataFrame([
                {
                    "equipo": team,
                    "let_requeridos": actual_map.get(team.strip().lower(), (0,0))[0],
                    "met_requeridos": actual_map.get(team.strip().lower(), (0,0))[1],
                }
                for team in equipos_req
            ])

            req_edit = st.data_editor(
                req_base,
                hide_index=True,
                use_container_width=True,
                disabled=["equipo"],
                column_config={
                    "equipo": st.column_config.TextColumn("Equipo"),
                    "let_requeridos": st.column_config.NumberColumn("LET requeridos", min_value=0, step=1, format="%d"),
                    "met_requeridos": st.column_config.NumberColumn("MET requeridos", min_value=0, step=1, format="%d"),
                },
                key="req_editor",
            )

            csave, cinfo = st.columns([1,3])
            if csave.button("💾 Guardar requerimientos", type="primary", key="save_req"):
                replace_requerimientos_df(req_edit[["equipo","let_requeridos","met_requeridos"]])
                clear_requerimientos_cache(); st.success("Requerimientos actualizados"); st.rerun()
            cinfo.info("Ejemplo: si 007 Delta requiere 4 LET y 2 MET, escribe 4 y 2. Si ese día hay 3 MET disponibles, 1 aparecerá como MET sobrante → POOL.")

            st.markdown("#### Lectura rápida")
            preview = req_edit.copy()
            # plantilla actual para contextualizar los requerimientos
            plantilla = load_empleados_df().copy()
            plantilla["funcion"] = plantilla["funcion"].astype(str).str.upper().str.strip()
            prev_rows=[]
            for _, rr in preview.iterrows():
                team=str(rr["equipo"])
                tt=plantilla[plantilla["equipo"].apply(canonical_team).astype(str).str.strip().str.lower()==team.strip().lower()]
                let_p=int((tt["funcion"]=="LET").sum()); met_p=int((tt["funcion"]=="MET").sum()); pool_p=int((tt["funcion"]=="POOL").sum())
                prev_rows.append({
                    "Equipo":team, "LET plantilla":let_p, "LET requeridos":int(rr["let_requeridos"]),
                    "Reserva LET":let_p-int(rr["let_requeridos"]),
                    "MET plantilla":met_p, "MET requeridos":int(rr["met_requeridos"]),
                    "MET base sobrantes":max(met_p-int(rr["met_requeridos"]),0),
                    "POOL asignado":pool_p,
                })
            st.dataframe(pd.DataFrame(prev_rows), hide_index=True, use_container_width=True)
        else:
            st.subheader("Eliminar incidencias")
            agenda = load_agenda()
            if agenda.empty: st.info("No hay registros.")
            else:
                work = agenda.copy(); work["fecha_iso"] = work["fecha"].dt.strftime("%Y-%m-%d")
                work["label"] = work.apply(lambda r: f"{r['fecha_iso']} · {r['numero']} · {r['nombre']} · {r['tipo']}", axis=1)
                opts = st.multiselect("Selecciona registros", work["label"].tolist())
                if st.button("Eliminar seleccionados", type="primary", key="del_rows", disabled=not bool(opts)):
                    chosen = work[work["label"].isin(opts)]
                    keys = set((str(r["numero"]), r["fecha_iso"], str(r["tipo"])) for _,r in chosen.iterrows())
                    n = delete_agenda_rows(keys); clear_agenda_cache(); st.success(f"Eliminados: {n}"); st.rerun()
