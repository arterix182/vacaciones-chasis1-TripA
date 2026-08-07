import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import datetime as dt
import calendar
import html as html_lib
from io import BytesIO
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, DataReturnMode, JsCode

from storage_gsheets_v4_4 import (
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

FUNCIONES = ["LET", "MET", "POOL"]
FUNCION_COLORS = {"LET":"#06b6d4", "MET":"#8b5cf6", "POOL":"#f59e0b", "":"#64748b"}
# Incidencias que hacen que una persona no cuente como disponible para la línea ese día.
# RET y TRB sí se consideran disponibles.
NO_DISPONIBLE = {"VAC","PSG","PPSG","FI","FJ","SAN","DEF","PAT","INC","SM","RM","EM","BJ","TE","PT"}

# Diseño general
st.markdown("""
<style>
    .block-container {padding-top: 1.35rem; padding-bottom: 2rem; max-width: 98%;}
    div[data-testid="stMetric"] {
        background: linear-gradient(145deg, rgba(15,23,42,.96), rgba(30,41,59,.92));
        border: 1px solid rgba(56,189,248,.22);
        border-radius: 16px;
        padding: 12px 16px;
        box-shadow: 0 10px 30px rgba(2,6,23,.22);
    }
    div[data-testid="stMetricLabel"] {color:#94a3b8;}
    div[data-testid="stMetricValue"] {color:#f8fafc; font-weight:800;}
    .matrix-hero {
        padding: 18px 22px;
        border-radius: 18px;
        background: linear-gradient(120deg,#0f172a 0%,#172554 48%,#0c4a6e 100%);
        border: 1px solid rgba(56,189,248,.30);
        box-shadow: 0 16px 44px rgba(2,6,23,.32);
        margin-bottom: 14px;
    }
    .matrix-title {font-size: 28px; font-weight: 900; color:#f8fafc; margin:0;}
    .matrix-sub {color:#bae6fd; margin-top:6px; font-size:14px;}
    .hint-box {
        background:rgba(14,116,144,.14);
        border:1px solid rgba(34,211,238,.28);
        border-radius:14px;
        padding:10px 14px;
        margin:8px 0 14px 0;
        color:#cffafe;
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

@st.cache_data(ttl=5)
def load_empleados():
    return get_empleados_dict()

@st.cache_data(ttl=5)
def load_empleados_df():
    return get_empleados_df()

@st.cache_data(ttl=5)
def load_agenda():
    df = get_agenda_df()
    if df is None or df.empty:
        return pd.DataFrame(columns=["numero","nombre","equipo","fecha","tipo"])
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    return df.dropna(subset=["fecha"])

@st.cache_data(ttl=10)
def load_requerimientos():
    df = get_requerimientos_df()
    if df is None or df.empty:
        return pd.DataFrame(columns=["equipo","let_requeridos","met_requeridos"])
    df = df.copy()
    df["equipo"] = df["equipo"].astype(str).str.strip()
    df["let_requeridos"] = pd.to_numeric(df["let_requeridos"], errors="coerce").fillna(0).astype(int)
    df["met_requeridos"] = pd.to_numeric(df["met_requeridos"], errors="coerce").fillna(0).astype(int)
    return df

def clear_cache():
    load_empleados.clear(); load_empleados_df.clear(); load_agenda.clear(); load_requerimientos.clear()

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
                clear_cache(); st.success("Registro guardado"); st.rerun()
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
    st.header("Calendario mensual")
    agenda = load_agenda(); hoy = dt.date.today()
    a, m = st.columns(2)
    anio_c = a.number_input("Año", value=hoy.year, min_value=hoy.year-1, max_value=hoy.year+3, key="c_anio")
    mes_c = m.selectbox("Mes", range(1,13), index=hoy.month-1, format_func=lambda x: MESES[x-1], key="c_mes")
    if agenda.empty:
        dfm = agenda.copy(); dfm["dia"] = []
    else:
        mask = (agenda["fecha"].dt.year == int(anio_c)) & (agenda["fecha"].dt.month == int(mes_c))
        dfm = agenda[mask].copy(); dfm["dia"] = dfm["fecha"].dt.day
    conteo = dfm.groupby("dia")["numero"].count().to_dict() if not dfm.empty else {}
    nombres = dfm.groupby("dia")["nombre"].apply(list).to_dict() if not dfm.empty else {}
    cal = calendar.Calendar(firstweekday=0); weeks = cal.monthdayscalendar(int(anio_c), int(mes_c))
    def color_count(n):
        return "#e5e7eb" if n == 0 else "#22c55e" if n == 1 else "#facc15" if n == 2 else "#ef4444"
    cal_html = "<div style='font-family:Arial,sans-serif'><table style='border-collapse:separate;border-spacing:6px;width:100%;table-layout:fixed'>"
    cal_html += "<tr>" + "".join(f"<th style='padding:8px;color:#94a3b8'>{x}</th>" for x in ["Lun","Mar","Mié","Jue","Vie","Sáb","Dom"]) + "</tr>"
    for week in weeks:
        cal_html += "<tr>"
        for day in week:
            if day == 0:
                cal_html += "<td></td>"; continue
            n = int(conteo.get(day, 0)); ns = nombres.get(day, [])
            lista = "<br>".join(html_lib.escape(str(x)) for x in ns[:3])
            cal_html += f"<td style='height:120px;vertical-align:top;padding:8px;border-radius:10px;background:{color_count(n)};color:#111827'><div style='font-weight:800;font-size:16px'>{day}</div><div style='font-size:12px'>{n} registro(s)</div><div style='font-size:11px;margin-top:6px;line-height:1.25'>{lista}</div></td>"
        cal_html += "</tr>"
    cal_html += "</table></div>"
    components.html(cal_html, height=90 + len(weeks)*145, scrolling=True)

if st.session_state.is_admin:
    with tab_matrix:
        st.markdown("""
        <div class="matrix-hero">
          <div class="matrix-title">⚡ Centro de Control de Incidencias</div>
          <div class="matrix-sub">Haz clic en una celda del empleado y del día. Selecciona la incidencia y se guardará automáticamente.</div>
        </div>
        """, unsafe_allow_html=True)

        empleados_df = load_empleados_df()
        agenda = load_agenda()
        req_df = load_requerimientos()
        req_map = {
            str(r["equipo"]).strip().lower(): {
                "let": int(r["let_requeridos"]),
                "met": int(r["met_requeridos"]),
            }
            for _, r in req_df.iterrows()
        } if not req_df.empty else {}
        hoy = dt.date.today()

        top1, top2, top3 = st.columns([1,1,2])
        anio_i = top1.number_input("Año", value=hoy.year, min_value=hoy.year-1, max_value=hoy.year+3, key="i_anio")
        mes_i = top2.selectbox("Mes", range(1,13), index=hoy.month-1, format_func=lambda x: MESES[x-1], key="i_mes")
        busqueda = top3.text_input("🔍 Buscar colaborador, número o equipo", key="i_buscar")

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

        p1,p2,p3,p4,p5 = st.columns(5)
        p1.metric("👥 Personas", total_personas)
        p2.metric("🔷 LET", total_let)
        p3.metric("🟣 MET", total_met)
        p4.metric("🟠 POOL", total_pool)
        p5.metric("⚪ Sin función", sin_funcion)

        req_let_total = sum(v.get("let",0) for v in req_map.values())
        req_met_total = sum(v.get("met",0) for v in req_map.values())
        q1,q2,q3 = st.columns(3)
        q1.metric("🎯 LET requeridos", req_let_total)
        q2.metric("🎯 MET requeridos", req_met_total)
        q3.metric("📋 Equipos configurados", len(req_map))

        # KPIs mensuales
        total_mes = len(agenda_m)
        vac_mes = int((agenda_m["codigo"] == "VAC").sum()) if not agenda_m.empty else 0
        faltas_mes = int(agenda_m["codigo"].isin(["FI","FJ"]).sum()) if not agenda_m.empty else 0
        permisos_mes = int(agenda_m["codigo"].isin(["PSG","PPSG","DEF","PAT"]).sum()) if not agenda_m.empty else 0
        incap_mes = int(agenda_m["codigo"].isin(["INC","SM","RM","EM"]).sum()) if not agenda_m.empty else 0

        k1,k2,k3,k4,k5 = st.columns(5)
        k1.metric("Incidencias del mes", total_mes)
        k2.metric("Vacaciones", vac_mes)
        k3.metric("Faltas", faltas_mes)
        k4.metric("Permisos", permisos_mes)
        k5.metric("Médicas / INC", incap_mes)

        st.markdown(
            '<div class="hint-box">🖱️ <b>Edición directa:</b> un clic en empleado + día abre el desplegable. '
            '📌 Nombres y función quedan congelados a la izquierda · 🔥 HOY se resalta · 🔍 puedes buscar persona, equipo o función. '
            'El administrador puede superar 3 personas por día. Selecciona <b>— Vacío —</b> para borrar.</div>',
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

        # Orden personalizado exacto
        def team_rank(team):
            return TEAM_RANK.get(str(team).strip().lower(), 999)

        edf["_team_rank"] = edf["equipo"].apply(team_rank)
        edf = edf.sort_values(["_team_rank","equipo","nombre"], kind="stable").reset_index(drop=True)

        # Valor actual por empleado/día.
        # Si por alguna razón hay más de uno, mostramos el último registro.
        current = {}
        if not agenda_m.empty:
            for _, r in agenda_m.sort_values("fecha").iterrows():
                current[(str(r["numero"]).strip(), int(r["dia"]))] = codigo_tipo(r["tipo"])

        # Construir matriz incluyendo filas separadoras de equipo
        rows = []
        known_teams = TEAM_ORDER.copy()
        extra_teams = [
            x for x in edf["equipo"].dropna().astype(str).unique().tolist()
            if x.strip().lower() not in TEAM_RANK
        ]
        teams_in_order = known_teams + sorted(extra_teams)

        for team in teams_in_order:
            grp = edf[edf["equipo"].astype(str).str.lower().str.strip() == team.lower().strip()]
            if grp.empty:
                continue

            grp_let = int((grp["funcion"] == "LET").sum())
            grp_met = int((grp["funcion"] == "MET").sum())
            grp_pool = int((grp["funcion"] == "POOL").sum())
            group_row = {
                "es_grupo": True,
                "Equipo": f"{team.upper()} · {len(grp)} PERSONAS · LET {grp_let} · MET {grp_met} · POOL {grp_pool}",
                "Función": "",
                "Colaborador": "",
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
                    "equipo_real": str(er["equipo"]),
                    "funcion_real": funcion,
                }
                for d in range(1, ultimo+1):
                    row[str(d)] = current.get((num, d), "")
                rows.append(row)

        matrix_df = pd.DataFrame(rows)

        incidence_options = [""] + list(INCIDENCIAS.keys())
        weekday_es = ["LUN","MAR","MIÉ","JUE","VIE","SÁB","DOM"]

        cell_style = JsCode("""
        function(params) {
            if (params.data && params.data.es_grupo) {
                return {
                    backgroundColor:'#cbd5e1',
                    color:'#0f172a',
                    fontWeight:'900',
                    borderColor:'#cbd5e1'
                };
            }
            const colors = {
                'VAC':'#10b981','PSG':'#fbbf24','PPSG':'#f59e0b',
                'FI':'#ef4444','FJ':'#eab308','SAN':'#dc2626',
                'RET':'#2563eb','DEF':'#64748b','PAT':'#0ea5e9',
                'INC':'#a855f7','SM':'#ec4899','RM':'#14b8a6',
                'EM':'#d946ef','BJ':'#6b7280','TE':'#60a5fa',
                'PT':'#f97316','TRB':'#15803d'
            };
            const v = params.value || '';
            if (!v) {
                return {
                    backgroundColor:'#1e293b',
                    color:'#94a3b8',
                    textAlign:'center',
                    borderColor:'#334155'
                };
            }
            return {
                backgroundColor: colors[v] || '#475569',
                color:'#ffffff',
                fontWeight:'900',
                textAlign:'center',
                borderRadius:'7px',
                border:'2px solid rgba(255,255,255,.16)'
            };
        }
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
                    rol = label.split()[0]
                    rol_df = edf[edf["funcion"] == rol]
                    unavailable_nums = set(dd[dd["codigo"].isin(NO_DISPONIBLE)]["numero"].astype(str).str.strip().tolist()) if not dd.empty else set()
                    value = int((~rol_df["numero"].astype(str).str.strip().isin(unavailable_nums)).sum())
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
        gb.configure_column("Equipo", pinned="left", width=250, minWidth=210, maxWidth=330, editable=False)
        gb.configure_column("Función", pinned="left", width=92, minWidth=82, maxWidth=105, editable=False, cellStyle=funcion_style)
        gb.configure_column("Colaborador", pinned="left", width=340, minWidth=280, editable=False)

        for d in range(1, ultimo+1):
            weekday = weekday_es[dt.date(int(anio_i), int(mes_i), d).weekday()]
            is_today = (int(anio_i) == hoy.year and int(mes_i) == hoy.month and d == hoy.day)
            gb.configure_column(
                str(d),
                header_name=(f"🔥 {d}\n{weekday}" if is_today else f"{d}\n{weekday}"),
                headerClass=("today-header" if is_today else ""),
                cellClass=("today-col" if is_today else ""),
                editable=editable_day,
                cellEditor="agSelectCellEditor",
                cellEditorParams={"values": incidence_options},
                cellStyle=cell_style,
                width=72,
                minWidth=66,
                maxWidth=82,
                wrapHeaderText=True,
                autoHeaderHeight=True,
            )

        gb.configure_grid_options(
            singleClickEdit=True,
            stopEditingWhenCellsLoseFocus=True,
            rowHeight=43,
            headerHeight=58,
            animateRows=True,
            suppressRowClickSelection=True,
            ensureDomOrder=True,
            getRowStyle=row_style,
            pinnedBottomRowData=pinned_rows,
        )

        custom_css = {
            ".ag-root-wrapper": {
                "border": "1px solid #334155 !important",
                "border-radius": "16px !important",
                "overflow": "hidden !important",
                "box-shadow": "0 18px 45px rgba(2,6,23,.32) !important",
            },
            ".ag-header": {
                "background-color": "#0b1220 !important",
                "border-bottom": "1px solid #334155 !important",
            },
            ".ag-header-cell": {
                "color": "#f8fafc !important",
                "font-weight": "800 !important",
                "border-right": "1px solid #334155 !important",
            },
            ".ag-cell": {
                "border-right": "1px solid #334155 !important",
                "border-bottom": "1px solid #334155 !important",
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
            height=820,
            key=f"inc_grid_{int(anio_i)}_{int(mes_i)}_{busqueda}",
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
                    action = set_admin_incidence(
                        numero=str(r["numero"]).strip(),
                        nombre=str(r["nombre_real"]).strip(),
                        equipo=str(r["equipo_real"]).strip(),
                        fecha=fecha_edit.isoformat(),
                        tipo=new_val,
                    )
                    clear_cache()
                    if new_val:
                        st.toast(f"✅ {new_val} guardado: {r['nombre_real']} · {fecha_edit.strftime('%d/%m/%Y')}")
                    else:
                        st.toast(f"🗑️ Incidencia eliminada: {r['nombre_real']} · {fecha_edit.strftime('%d/%m/%Y')}")
                    st.rerun()
                except Exception as e:
                    st.error(f"No se pudo guardar el cambio: {e}")

        # Leyenda
        legend_html = "".join(
            f"<span style='display:inline-block;background:{color};color:white;padding:6px 11px;"
            f"border-radius:16px;margin:3px;font-size:11px;font-weight:800'>{cod} — {html_lib.escape(desc)}</span>"
            for cod,(desc,color) in INCIDENCIAS.items()
        )
        st.markdown(legend_html, unsafe_allow_html=True)

        # Resumen por día
        st.markdown("---")
        st.subheader("📊 Resumen diario de incidencias")

        if agenda_m.empty:
            st.info("No hay incidencias en el mes seleccionado.")
        else:
            resumen_rows = []
            for d in range(1, ultimo+1):
                dd = agenda_m[agenda_m["dia"] == d]
                codes = dd["codigo"] if not dd.empty else pd.Series(dtype=str)
                resumen_rows.append({
                    "Día": d,
                    "Total": len(dd),
                    "Vacaciones": int((codes == "VAC").sum()),
                    "Faltas": int(codes.isin(["FI","FJ"]).sum()),
                    "Permisos": int(codes.isin(["PSG","PPSG","DEF","PAT"]).sum()),
                    "Sanciones": int((codes == "SAN").sum()),
                    "Retardos": int((codes == "RET").sum()),
                    "Incapacidad / Médico": int(codes.isin(["INC","SM","RM","EM"]).sum()),
                    "Otros": int(codes.isin(["BJ","TE","PT","TRB"]).sum()),
                })
            resumen_df = pd.DataFrame(resumen_rows)
            st.dataframe(resumen_df, hide_index=True, use_container_width=True, height=330)

            dia_res = st.selectbox(
                "Detalle de un día",
                range(1, ultimo+1),
                index=min(hoy.day, ultimo)-1,
                format_func=lambda d: f"{d:02d} de {MESES[int(mes_i)-1]}",
                key="res_dia_select"
            )
            ddf = agenda_m[agenda_m["dia"] == int(dia_res)].copy()
            if ddf.empty:
                st.info("Sin incidencias ese día.")
            else:
                a,b,c,d,e = st.columns(5)
                a.metric("Total incidencias", len(ddf))
                b.metric("VAC", int((ddf["codigo"]=="VAC").sum()))
                c.metric("Faltas", int(ddf["codigo"].isin(["FI","FJ"]).sum()))
                d.metric("Permisos", int(ddf["codigo"].isin(["PSG","PPSG","DEF","PAT"]).sum()))
                e.metric("INC / Médico", int(ddf["codigo"].isin(["INC","SM","RM","EM"]).sum()))

                unavailable = set(ddf[ddf["codigo"].isin(NO_DISPONIBLE)]["numero"].astype(str).str.strip().tolist())
                base_staff = empleados_df.copy()
                base_staff["funcion"] = base_staff["funcion"].astype(str).str.strip().str.upper()
                let_libres = int(((base_staff["funcion"]=="LET") & ~base_staff["numero"].astype(str).str.strip().isin(unavailable)).sum())
                met_libres = int(((base_staff["funcion"]=="MET") & ~base_staff["numero"].astype(str).str.strip().isin(unavailable)).sum())
                pool_libres = int(((base_staff["funcion"]=="POOL") & ~base_staff["numero"].astype(str).str.strip().isin(unavailable)).sum())

                # Balance por equipo: disponibles vs requerimiento configurado
                balance_rows = []
                met_sobrantes_total = 0
                deficit_let_total = 0
                deficit_met_total = 0
                pool_operativo_total = 0
                equipos_calc = TEAM_ORDER + sorted([
                    x for x in base_staff["equipo"].dropna().astype(str).unique().tolist()
                    if x.strip().lower() not in TEAM_RANK
                ])
                for team in equipos_calc:
                    team_staff = base_staff[base_staff["equipo"].astype(str).str.strip().str.lower() == team.strip().lower()]
                    if team_staff.empty:
                        continue
                    nums_team = team_staff["numero"].astype(str).str.strip()
                    disp_mask = ~nums_team.isin(unavailable)
                    let_total_t = int((team_staff["funcion"] == "LET").sum())
                    met_total_t = int((team_staff["funcion"] == "MET").sum())
                    pool_total_t = int((team_staff["funcion"] == "POOL").sum())
                    let_disp_t = int(((team_staff["funcion"] == "LET") & disp_mask).sum())
                    met_disp_t = int(((team_staff["funcion"] == "MET") & disp_mask).sum())
                    pool_disp_t = int(((team_staff["funcion"] == "POOL") & disp_mask).sum())
                    req = req_map.get(team.strip().lower(), {"let":0,"met":0})
                    req_let = int(req.get("let",0)); req_met = int(req.get("met",0))
                    bal_let = let_disp_t - req_let
                    bal_met = met_disp_t - req_met
                    met_a_pool = max(bal_met, 0)
                    def_let = max(-bal_let, 0)
                    def_met = max(-bal_met, 0)
                    pool_potencial = pool_disp_t + met_a_pool
                    met_sobrantes_total += met_a_pool
                    deficit_let_total += def_let
                    deficit_met_total += def_met
                    pool_operativo_total += pool_potencial
                    status_parts = []
                    if def_let: status_parts.append(f"FALTAN {def_let} LET")
                    if def_met: status_parts.append(f"FALTAN {def_met} MET")
                    status = "🔴 " + " · ".join(status_parts) if status_parts else "🟢 CUBIERTO"
                    balance_rows.append({
                        "Equipo": team,
                        "LET plantilla": let_total_t,
                        "LET disponibles": let_disp_t,
                        "LET requeridos": req_let,
                        "Balance LET": bal_let,
                        "MET plantilla": met_total_t,
                        "MET disponibles": met_disp_t,
                        "MET requeridos": req_met,
                        "MET sobrantes → POOL": met_a_pool,
                        "POOL asignado disponible": pool_disp_t,
                        "POOL potencial": pool_potencial,
                        "Estado": status,
                    })

                r1,r2,r3,r4,r5 = st.columns(5)
                r1.metric("🔷 LET disponibles", let_libres)
                r2.metric("🟣 MET disponibles", met_libres)
                r3.metric("🟠 POOL asignado", pool_libres)
                r4.metric("➡️ MET sobrantes → POOL", met_sobrantes_total)
                r5.metric("🧰 POOL potencial", pool_operativo_total)

                d1,d2 = st.columns(2)
                d1.metric("⚠️ Déficit LET total", deficit_let_total)
                d2.metric("⚠️ Déficit MET total", deficit_met_total)

                st.markdown("#### ⚙️ Cobertura operativa por equipo")
                if not req_map:
                    st.warning("Aún no has configurado requerimientos. Ve a 🛠️ Administración → Requerimientos por equipo.")
                if balance_rows:
                    balance_df = pd.DataFrame(balance_rows)
                    st.dataframe(balance_df, hide_index=True, use_container_width=True, height=360)

                st.markdown("#### Incidencias del día")
                st.dataframe(
                    ddf[["numero","nombre","equipo","codigo","tipo"]].sort_values(["equipo","nombre"]),
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
                clear_cache(); st.success("Funciones actualizadas"); st.rerun()

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
                    clear_cache(); st.success("Empleado agregado"); st.rerun()
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
                        replace_empleados_df(norm); clear_cache(); st.success("Lista actualizada"); st.rerun()
                else: st.error("El archivo debe tener: numero, nombre, equipo. La columna funcion es opcional.")
        elif sec == "Requerimientos por equipo":
            st.subheader("🎯 Requerimiento mínimo por equipo")
            st.caption("Define cuántos LET y MET necesita cada equipo para operar. La app calculará faltantes y MET sobrantes que pueden pasar a POOL.")

            req_actual = load_requerimientos().copy()
            emp_actual = load_empleados_df().copy()
            extra_teams = [
                x for x in emp_actual["equipo"].dropna().astype(str).unique().tolist()
                if x.strip().lower() not in TEAM_RANK
            ]
            equipos_req = TEAM_ORDER + sorted(extra_teams)
            actual_map = {
                str(r["equipo"]).strip().lower(): (int(r["let_requeridos"]), int(r["met_requeridos"]))
                for _, r in req_actual.iterrows()
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
                clear_cache(); st.success("Requerimientos actualizados"); st.rerun()
            cinfo.info("Ejemplo: si 007 Delta requiere 4 LET y 2 MET, escribe 4 y 2. Si ese día hay 3 MET disponibles, 1 aparecerá como MET sobrante → POOL.")

            st.markdown("#### Lectura rápida")
            preview = req_edit.copy()
            # plantilla actual para contextualizar los requerimientos
            plantilla = load_empleados_df().copy()
            plantilla["funcion"] = plantilla["funcion"].astype(str).str.upper().str.strip()
            prev_rows=[]
            for _, rr in preview.iterrows():
                team=str(rr["equipo"])
                tt=plantilla[plantilla["equipo"].astype(str).str.strip().str.lower()==team.strip().lower()]
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
                    n = delete_agenda_rows(keys); clear_cache(); st.success(f"Eliminados: {n}"); st.rerun()
