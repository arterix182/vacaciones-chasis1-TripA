import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import datetime as dt
import calendar
import html as html_lib
from io import BytesIO

from storage_gsheets_v4 import (
    get_empleados_dict, get_empleados_df, get_agenda_df,
    append_agenda_row_safe, append_agenda_row_admin,
    delete_agenda_rows, replace_empleados_df, append_empleados_rows
)

st.set_page_config(page_title="Vacaciones CH-1", page_icon="📅", layout="wide")

MESES = ["Enero","Febrero","Marzo","Abril","Mayo","Junio","Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"]
ADMIN_PASSWORD = st.secrets.get("admin_password", "CH1-Admin-2025")

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

def clear_cache():
    load_empleados.clear(); load_empleados_df.clear(); load_agenda.clear()

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
        st.success(f"{emp['nombre']} — Equipo: {emp['equipo']}")
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
        st.header("Matriz mensual de incidencias")
        st.caption("Vista privada del administrador. Aquí puedes rebasar el límite de 3 cuando sea necesario.")
        empleados_df = load_empleados_df(); agenda = load_agenda(); hoy = dt.date.today()
        top1, top2, top3 = st.columns([1,1,2])
        anio_i = top1.number_input("Año", value=hoy.year, min_value=hoy.year-1, max_value=hoy.year+3, key="i_anio")
        mes_i = top2.selectbox("Mes", range(1,13), index=hoy.month-1, format_func=lambda x: MESES[x-1], key="i_mes")
        busqueda = top3.text_input("🔍 Buscar colaborador", key="i_buscar")
        ultimo = calendar.monthrange(int(anio_i), int(mes_i))[1]
        agenda_m = agenda[(agenda["fecha"].dt.year == int(anio_i)) & (agenda["fecha"].dt.month == int(mes_i))].copy() if not agenda.empty else agenda.copy()

        with st.expander("➕ Agregar incidencia como administrador", expanded=False):
            ca, cb, cc, cd = st.columns([1,2,1,2])
            num_admin = ca.text_input("Número de empleado", key="adm_num").strip()
            emp_admin = load_empleados().get(num_admin)
            if emp_admin: cb.success(f"{emp_admin['nombre']} · {emp_admin['equipo']}")
            else: cb.info("Ingresa un número válido")
            fecha_admin = cc.date_input("Fecha", value=dt.date(int(anio_i), int(mes_i), min(hoy.day, ultimo)), key="adm_fecha")
            opciones = [f"{cod} — {desc}" for cod,(desc,_) in INCIDENCIAS.items()]
            sel = cd.selectbox("Incidencia", opciones, key="adm_inc"); cod_sel = sel.split(" — ",1)[0]
            st.warning("Modo administrador: puede superar 3 personas por día y repetir equipo.")
            if st.button("Guardar incidencia administrativa", key="adm_guardar", type="primary", disabled=not bool(emp_admin)):
                append_agenda_row_admin({"numero": num_admin,"nombre": emp_admin["nombre"],"equipo": emp_admin["equipo"],"fecha": fecha_admin.isoformat(),"tipo": cod_sel})
                clear_cache(); st.success("Incidencia agregada"); st.rerun()

        edf = empleados_df.copy()
        if busqueda:
            q = busqueda.lower().strip()
            edf = edf[edf["nombre"].str.lower().str.contains(q, na=False) | edf["numero"].str.lower().str.contains(q, na=False) | edf["equipo"].str.lower().str.contains(q, na=False)]

        cell_map = {}
        if not agenda_m.empty:
            agenda_m["dia"] = agenda_m["fecha"].dt.day
            for _, r in agenda_m.iterrows():
                cell_map.setdefault((str(r["numero"]).strip(), int(r["dia"])), []).append(str(r["tipo"]).strip())
        count_day = {}; count_day_type = {}
        if not agenda_m.empty:
            agenda_m["codigo"] = agenda_m["tipo"].apply(codigo_tipo)
            count_day = agenda_m.groupby("dia")["numero"].count().to_dict()
            count_day_type = agenda_m.groupby(["dia","codigo"]).size().to_dict()

        day_headers = "".join(f"<th class='day'><div>{d}</div><small>{calendar.day_abbr[dt.date(int(anio_i),int(mes_i),d).weekday()]}</small></th>" for d in range(1, ultimo+1))
        rows_html = ""
        for equipo, grp in edf.sort_values(["equipo","nombre"]).groupby("equipo", sort=True):
            rows_html += f"<tr class='group'><td colspan='{ultimo+1}'>{html_lib.escape(str(equipo))}</td></tr>"
            for _, er in grp.iterrows():
                num = str(er["numero"]).strip(); nombre = html_lib.escape(str(er["nombre"]))
                namecell = f"<td class='person'><span class='num'>{html_lib.escape(num)}</span><span>{nombre}</span></td>"
                cells = ""
                for day in range(1, ultimo+1):
                    badges = ""
                    for t in cell_map.get((num,day), []):
                        cod = codigo_tipo(t); color = color_tipo(t)
                        badges += f"<span class='badge' style='background:{color}' title='{html_lib.escape(etiqueta_tipo(t))}'>{html_lib.escape(cod)}</span>"
                    cells += f"<td class='cell'>{badges}</td>"
                rows_html += f"<tr>{namecell}{cells}</tr>"
        footer1 = "<tr class='footer'><td class='person'><b>Σ Incidencias</b></td>" + "".join(f"<td class='sum'>{int(count_day.get(d,0))}</td>" for d in range(1,ultimo+1)) + "</tr>"
        footer2 = "<tr class='footer2'><td class='person'><b>Detalle día</b></td>"
        for day in range(1, ultimo+1):
            parts=[]
            for cod in INCIDENCIAS:
                n = int(count_day_type.get((day,cod),0))
                if n: parts.append(f"{cod}:{n}")
            footer2 += f"<td class='mini'>{'<br>'.join(parts)}</td>"
        footer2 += "</tr>"
        legend = "".join(f"<span class='legend' style='background:{color}'>{cod} — {html_lib.escape(desc)}</span>" for cod,(desc,color) in INCIDENCIAS.items())
        full_html = f"""
        <html><head><style>
        body{{margin:0;background:#0f172a;color:#e5e7eb;font-family:Arial,sans-serif}}
        .wrap{{overflow:auto;max-height:720px;border:1px solid #334155;border-radius:12px}}
        table{{border-collapse:collapse;min-width:{500+ultimo*58}px;width:100%}}
        th,td{{border:1px solid #334155}}
        thead th{{position:sticky;top:0;z-index:4;background:#111827}}
        .person{{position:sticky;left:0;z-index:3;background:#1e293b;min-width:310px;padding:7px 10px;white-space:nowrap}}
        thead .person{{z-index:6;background:#111827}}
        .num{{display:inline-block;background:#dbeafe;color:#1d4ed8;border-radius:6px;padding:3px 7px;margin-right:8px;font-weight:700}}
        .day{{min-width:56px;padding:5px;text-align:center}} .day small{{color:#94a3b8;font-size:9px}}
        .cell{{height:36px;min-width:56px;text-align:center;background:#1f2937}}
        .badge{{display:inline-block;color:white;font-size:10px;font-weight:800;border-radius:5px;padding:4px;margin:1px}}
        .group td{{background:#cbd5e1;color:#0f172a;font-weight:800;height:22px;padding-left:10px}}
        .footer td,.footer2 td{{background:#111827;font-weight:700}} .sum{{text-align:center;color:#f8fafc}}
        .mini{{font-size:9px;text-align:center;color:#93c5fd;line-height:1.15}}
        .legendbar{{padding:12px 4px;display:flex;gap:7px;flex-wrap:wrap}} .legend{{color:white;padding:6px 10px;border-radius:16px;font-size:11px;font-weight:700}}
        </style></head><body><div class='wrap'><table><thead><tr><th class='person'>Colaborador</th>{day_headers}</tr></thead><tbody>{rows_html}{footer1}{footer2}</tbody></table></div><div class='legendbar'>{legend}</div></body></html>
        """
        components.html(full_html, height=860, scrolling=False)

        st.subheader("Resumen por día")
        dia_res = st.number_input("Día a revisar", min_value=1, max_value=ultimo, value=min(hoy.day, ultimo), key="res_dia")
        ddf = agenda_m[agenda_m["fecha"].dt.day == int(dia_res)].copy() if not agenda_m.empty else agenda_m.copy()
        if ddf.empty:
            st.info("Sin incidencias ese día.")
        else:
            ddf["Código"] = ddf["tipo"].apply(codigo_tipo)
            resumen = ddf.groupby("Código").size().reset_index(name="Cantidad")
            resumen["Incidencia"] = resumen["Código"].apply(lambda x: INCIDENCIAS.get(x,(x,""))[0])
            st.dataframe(resumen[["Código","Incidencia","Cantidad"]], hide_index=True, use_container_width=True)
            st.dataframe(ddf[["numero","nombre","equipo","tipo"]], hide_index=True, use_container_width=True)

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
        sec = st.radio("Sección", ["Empleados", "Eliminar incidencias"], horizontal=True)
        if sec == "Empleados":
            st.subheader("Agregar más personas")
            with st.form("nuevo_empleado"):
                c1,c2,c3 = st.columns(3)
                nnum = c1.text_input("Número de empleado"); nnom = c2.text_input("Nombre completo"); neq = c3.text_input("Equipo")
                ok = st.form_submit_button("Agregar empleado")
            if ok:
                if not nnum or not nnom or not neq: st.error("Completa los 3 datos.")
                else:
                    append_empleados_rows(pd.DataFrame([{"numero":nnum.strip(),"nombre":nnom.strip(),"equipo":neq.strip()}]))
                    clear_cache(); st.success("Empleado agregado"); st.rerun()
            st.subheader("Importar empleados desde Excel/CSV")
            up = st.file_uploader("Archivo con columnas numero, nombre, equipo", type=["csv","xlsx"], key="emp_up")
            if up is not None:
                dfup = pd.read_csv(up) if up.name.lower().endswith(".csv") else pd.read_excel(up)
                cols = {c.lower().strip():c for c in dfup.columns}
                if all(x in cols for x in ["numero","nombre","equipo"]):
                    norm = pd.DataFrame({"numero":dfup[cols["numero"]].astype(str).str.strip(),"nombre":dfup[cols["nombre"]].astype(str).str.strip(),"equipo":dfup[cols["equipo"]].astype(str).str.strip()})
                    st.dataframe(norm.head(20), use_container_width=True)
                    if st.button("Reemplazar lista completa", key="replace_emp"):
                        replace_empleados_df(norm); clear_cache(); st.success("Lista actualizada"); st.rerun()
                else: st.error("El archivo debe tener: numero, nombre, equipo")
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
