# (archivo) app_vacaciones_cloud_v3_3.py
# Vacaciones CH-1 (Cloud) v3.3 — Reportes mensuales por equipo + validación en servidor
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import datetime as dt
import calendar
from io import BytesIO

from storage_gsheets_v3 import (
    get_empleados_dict, get_empleados_df,
    get_agenda_df, append_agenda_row_safe, replace_agenda_df,
    append_empleados_rows, replace_empleados_df,
)

st.set_page_config(page_title="Vacaciones CH-1 (Cloud)", page_icon="📅", layout="wide")

MESES = ["Enero","Febrero","Marzo","Abril","Mayo","Junio","Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"]
DIAS = ["Lun","Mar","Mié","Jue","Vie","Sáb","Dom"]
ADMIN_PASSWORD = st.secrets.get("admin_password", "CH1-Admin-2025")

@st.cache_data(ttl=5)
def load_empleados():
    return get_empleados_dict()

@st.cache_data(ttl=5)
def load_agenda_df():
    df = get_agenda_df()
    if not df.empty:
        df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
        df = df.dropna(subset=["fecha"])
    return df

def clear_cache():
    load_empleados.clear()
    load_agenda_df.clear()

if "is_admin" not in st.session_state:
    st.session_state.is_admin = False

with st.sidebar:
    st.header("Vacaciones CH-1 (Cloud)")
    with st.expander("🔑 Administrador", expanded=False):
        if not st.session_state.is_admin:
            admin_pwd = st.text_input("Contraseña admin", type="password", key="admin_pwd")
            if st.button("Entrar como admin", key="btn_admin_login"):
                if admin_pwd == ADMIN_PASSWORD:
                    st.session_state.is_admin = True
                    st.success("Sesión de administrador activa")
                else:
                    st.error("Contraseña incorrecta")
        else:
            st.success("Sesión admin activa")
            if st.button("Cerrar sesión admin", key="btn_admin_logout"):
                st.session_state.is_admin = False

tab1, tab2, tab3, tab4 = st.tabs(["📝 Captura", "📅 Calendario / Exportación", "🧰 Admin avanzado", "📊 Reportes"])

# ---------------- Captura ----------------
with tab1:
    st.subheader("Captura de solicitudes")
    empleados_db = load_empleados()
    agenda_df = load_agenda_df()

    c1, c2 = st.columns(2)
    with c1:
        password = st.text_input("Contraseña (usuario)", type="password", key="pwd_user")
    with c2:
        numero_empleado = st.text_input("Número de empleado", key="num_emp")

    if password and numero_empleado in empleados_db:
        emp = empleados_db[numero_empleado]
        st.success(f"{emp['nombre']} — Equipo: {emp['equipo']}")

        hoy = dt.date.today()
        c3, c4, c5 = st.columns(3)
        with c3:
            anio = st.number_input("Año", min_value=hoy.year, max_value=hoy.year+2, value=hoy.year, step=1, key="anio_cap")
        with c4:
            mes = st.selectbox("Mes", list(range(1,13)), index=hoy.month-1, format_func=lambda m: MESES[m-1], key="mes_cap")
        dias_mes = calendar.monthrange(int(anio), int(mes))[1]
        with c5:
            dia = st.selectbox("Día", list(range(1, dias_mes+1)), index=min(hoy.day-1, dias_mes-1), key="dia_cap")

        tipo = st.selectbox("Tipo", ["Vacaciones", "Permiso", "Sanción"], key="tipo_cap")
        fecha = dt.date(int(anio), int(mes), int(dia))

        personas_mismo_dia = agenda_df[agenda_df["fecha"].dt.date == fecha]
        if len(personas_mismo_dia) >= 3:
            st.warning("Seleccione otro día, ya que el día que solicitas ya está llena la agenda")
        elif any(personas_mismo_dia["equipo"] == emp["equipo"]):
            st.warning("No puedes seleccionar este día porque ya hay alguien de tu equipo registrado")

        colA, colB = st.columns([1,2])
        with colA:
            if st.button("Registrar día", key="btn_registrar"):
                try:
                    append_agenda_row_safe({
                        "numero": numero_empleado,
                        "nombre": emp["nombre"],
                        "equipo": emp["equipo"],
                        "fecha": fecha.isoformat(),
                        "tipo": tipo
                    })
                    clear_cache()
                    st.success("Día registrado exitosamente")
                except ValueError as e:
                    code = str(e)
                    if "LLENO" in code:
                        st.warning("Seleccione otro día, ya que el día que solicitas ya está llena la agenda")
                    elif "MISMO_EQUIPO" in code:
                        st.warning("No puedes seleccionar este día porque ya hay alguien de tu equipo registrado")
                    elif "FORMATO_FECHA" in code:
                        st.error("Fecha inválida. Intenta de nuevo.")
                    elif "RACE_CONDITION" in code:
                        st.warning("Se alcanzó el límite de 3 justo ahora. Intenta con otro día.")
                    else:
                        st.error(f"Error registrando: {e}")
        with colB:
            st.info(
                f"Registrados el {fecha.isoformat()}: "
                + (", ".join(personas_mismo_dia['nombre'].tolist()) if not personas_mismo_dia.empty else "ninguno")
            )

        if not personas_mismo_dia.empty:
            st.write("**Detalle del día**")
            st.table(personas_mismo_dia[["numero","nombre","equipo","tipo"]])

    else:
        if password and numero_empleado:
            st.error("No se encontró el número de empleado. Verifica que esté cargado en la hoja 'empleados'.")
        st.info("Ingresa tu contraseña y un número de empleado válido para capturar.")

# ---------------- Calendario / Exportación ----------------
with tab2:
    st.subheader("Calendario mensual y exportación")
    empleados_db = load_empleados()
    df = load_agenda_df()

    hoy = dt.date.today()
    c1, c2, c3, c4 = st.columns([1,1,1,1])
    with c1:
        anioC = st.number_input("Año", value=hoy.year, min_value=hoy.year-1, max_value=hoy.year+3, key="anio_cal")
    with c2:
        mesC = st.selectbox("Mes", list(range(1,13)), index=hoy.month-1, format_func=lambda m: MESES[m-1], key="mes_cal")
    with c3:
        equipos = sorted({ v["equipo"] for v in empleados_db.values() })
        equipo_sel = st.selectbox("Equipo", ["Todos"] + equipos, key="equipo_cal")
    with c4:
        solo_llenos = st.checkbox("Solo días llenos (3)", value=False, key="llenos_cal")

    dias_mes = calendar.monthrange(int(anioC), int(mesC))[1]
    f_ini_date = dt.date(int(anioC), int(mesC), 1)
    f_fin_date = dt.date(int(anioC), int(mesC), dias_mes)

    if not df.empty:
        fechas_date = df["fecha"].dt.date
        mask = (fechas_date >= f_ini_date) & (fechas_date <= f_fin_date)
        df_mes = df[mask].copy()
        df_mes["dia"] = df_mes["fecha"].dt.day
    else:
        df_mes = df.copy()
        df_mes["dia"] = []

    if equipo_sel != "Todos" and not df_mes.empty:
        df_eq = df_mes[df_mes["equipo"] == equipo_sel]
    else:
        df_eq = pd.DataFrame(columns=df_mes.columns)

    conteo_total = df_mes.groupby("dia")["numero"].count().to_dict() if not df_mes.empty else {}
    conteo_equipo = df_eq.groupby("dia")["numero"].count().to_dict() if not df_eq.empty else {}

    def color_for(c):
        if not c or c == 0: return "#e9ecef"
        if c == 1: return "#2ecc71"
        if c == 2: return "#f1c40f"
        return "#e74c3c"

    cal = calendar.Calendar(firstweekday=0)
    weeks = cal.monthdayscalendar(int(anioC), int(mesC))

    legend = """
    <div style='display:flex; gap:12px; align-items:center; font-size:14px;'>
      <div style='display:flex; align-items:center; gap:6px;'><span style='display:inline-block;width:16px;height:16px;background:#e9ecef;border:1px solid #ccc;'></span> 0</div>
      <div style='display:flex; align-items:center; gap:6px;'><span style='display:inline-block;width:16px;height:16px;background:#2ecc71;'></span> 1</div>
      <div style='display:flex; align-items:center; gap:6px;'><span style='display:inline-block;width:16px;height:16px;background:#f1c40f;'></span> 2</div>
      <div style='display:flex; align-items:center; gap:6px;'><span style='display:inline-block;width:16px;height:16px;background:#e74c3c;'></span> 3</div>
      <div style='display:flex; align-items:center; gap:6px;'><span style='display:inline-block;width:12px;height:12px;border-radius:50%;background:#00bcd4;'></span> Equipo seleccionado</div>
    </div>
    """
    st.markdown(legend, unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

    html = "<table style='border-collapse:separate;border-spacing:8px;width:100%;table-layout:fixed;'>"
    html += "<tr>" + "".join([f"<th style='text-align:center;font-weight:600;color:#333'>{d}</th>" for d in DIAS]) + "</tr>"
    for week in weeks:
        html += "<tr>"
        for d in week:
            if d == 0:
                html += "<td></td>"
                continue
            count = int(conteo_total.get(d, 0))
            if solo_llenos and count < 3:
                html += "<td style='height:90px'></td>"
                continue
            color = color_for(count)
            dot = ""
            if equipo_sel != "Todos" and conteo_equipo.get(d, 0) > 0:
                dot = "<div style='margin-top:6px;'><span style='display:inline-block;width:10px;height:10px;border-radius:50%;background:#00bcd4;'></span></div>"
            cell = f"""
            <td style='vertical-align:top; padding:8px; background:{color}; border:1px solid #ddd; border-radius:10px; text-align:center; height:90px;'>
              <div style='font-weight:700;color:#1b1e23;font-size:16px'>{d}</div>
              <div style='font-size:12px;color:#1b1e23'>{count} registro(s)</div>
              {dot}
            </td>
            """
            html += cell
        html += "</tr>"
    html += "</table>"

    cal_height = 80 + (len(weeks) * 120)
    components.html(html, height=cal_height, scrolling=True)

# ---------------- Admin avanzado ----------------
with tab3:
    st.subheader("🧰 Admin avanzado")
    if not st.session_state.is_admin:
        st.info("Inicia sesión como admin para usar estas funciones.")
    else:
        sec = st.radio("Selecciona sección", ["Importar HISTÓRICO (Agenda)", "Importar EMPLEADOS", "Diagnóstico"], horizontal=True)
        if sec == "Importar EMPLEADOS":
            st.markdown("Sube **CSV/Excel** con columnas: `numero, nombre, equipo`.")
            upE = st.file_uploader("Archivo de empleados", type=["csv","xlsx"], key="emp_upload")
            modeE = st.radio("Modo", ["Anexar", "Reemplazar TODO"], index=0, horizontal=True)

            def norm_emp(df: pd.DataFrame) -> pd.DataFrame:
                cols_map = {c.lower().strip(): c for c in df.columns}
                def pick(*names):
                    for n in names:
                        if n in cols_map:
                            return cols_map[n]
                    return None
                cn = pick("numero","id","empleado","num","número")
                nn = pick("nombre","name")
                eq = pick("equipo","team","depto","departamento")
                if any(x is None for x in [cn,nn,eq]):
                    st.error("Faltan columnas requeridas (numero, nombre, equipo).")
                    return pd.DataFrame(columns=["numero","nombre","equipo"])
                out = pd.DataFrame({
                    "numero": df[cn].astype(str).str.strip(),
                    "nombre": df[nn].astype(str).str.strip(),
                    "equipo": df[eq].astype(str).str.strip(),
                })
                return out

            if upE is not None:
                try:
                    if upE.name.lower().endswith(".csv"):
                        df_in = pd.read_csv(upE)
                    else:
                        df_in = pd.read_excel(upE)
                    df_norm = norm_emp(df_in)
                    if df_norm.empty:
                        st.warning("No hay filas válidas.")
                    else:
                        st.dataframe(df_norm.head(10), use_container_width=True)
                        if st.button("Confirmar empleados", type="primary", key="btn_import_emp"):
                            if modeE.startswith("Anexar"):
                                append_empleados_rows(df_norm)
                                clear_cache()
                                st.success(f"Empleados agregados: {len(df_norm)}")
                            else:
                                replace_empleados_df(df_norm)
                                clear_cache()
                                st.success(f"Empleados reemplazados: {len(df_norm)}")
                except Exception as e:
                    st.error(f"Error importando empleados: {e}")
            else:
                st.info("Selecciona archivo de empleados para importar.")

        elif sec == "Importar HISTÓRICO (Agenda)":
            st.markdown("Sube **JSON/CSV/Excel** con columnas: `numero, nombre, equipo, fecha, tipo`.")
            up = st.file_uploader("Archivo histórico", type=["json","csv","xlsx"], key="hist_upload")
            mode = st.radio("Modo de importación", ["Anexar (evita duplicados)", "Reemplazar TODO"], index=0, horizontal=True)

            def norm_agenda(df: pd.DataFrame) -> pd.DataFrame:
                cols_map = {c.lower().strip(): c for c in df.columns}
                def pick(*names):
                    for n in names:
                        if n in cols_map:
                            return cols_map[n]
                    return None
                col_num = pick("numero","número","id","empleado","num")
                col_nom = pick("nombre","name","empleado_nombre")
                col_eq  = pick("equipo","team","depto","departamento")
                col_fec = pick("fecha","date","dia","día")
                col_tip = pick("tipo","motivo","clase")
                required = [col_num, col_nom, col_eq, col_fec, col_tip]
                if any(x is None for x in required):
                    st.error("Faltan columnas requeridas.")
                    return pd.DataFrame(columns=["numero","nombre","equipo","fecha","tipo"])
                out = pd.DataFrame({
                    "numero": df[col_num].astype(str).str.strip(),
                    "nombre": df[col_nom].astype(str).str.strip(),
                    "equipo": df[col_eq].astype(str).str.strip(),
                    "fecha": pd.to_datetime(df[col_fec], errors="coerce"),
                    "tipo":   df[col_tip].astype(str).str.strip().replace({"Sansión":"Sanción"})
                }).dropna(subset=["fecha"])
                return out

            if up is not None:
                try:
                    if up.name.lower().endswith(".json"):
                        import json
                        raw = json.load(up)
                        if isinstance(raw, dict) and "agenda" in raw:
                            raw = raw["agenda"]
                        df_in = pd.DataFrame(raw)
                    elif up.name.lower().endswith(".csv"):
                        df_in = pd.read_csv(up)
                    else:
                        df_in = pd.read_excel(up)

                    df_norm = norm_agenda(df_in)
                    if df_norm.empty:
                        st.warning("No hay filas válidas.")
                    else:
                        st.dataframe(df_norm.head(10), use_container_width=True)
                        if st.button("Confirmar importación", type="primary", key="btn_import_hist"):
                            if mode.startswith("Anexar"):
                                actual = load_agenda_df()
                                if not actual.empty:
                                    actual["clave"] = actual["numero"].astype(str)+"|"+actual["fecha"].dt.strftime("%Y-%m-%d")+"|"+actual["tipo"].astype(str)
                                else:
                                    actual = pd.DataFrame(columns=["clave"])
                                df_norm["clave"] = df_norm["numero"].astype(str)+"|"+df_norm["fecha"].dt.strftime("%Y-%m-%d")+"|"+df_norm["tipo"].astype(str)
                                nuevos = df_norm[~df_norm["clave"].isin(actual.get("clave", pd.Series([], dtype=str)))].copy()
                                if nuevos.empty:
                                    st.info("No hay filas nuevas (todo eran duplicados).")
                                else:
                                    from storage_gsheets_v3 import _ws, AGENDA_HEADERS
                                    ws = _ws("agenda", AGENDA_HEADERS)
                                    nuevos2 = nuevos.copy()
                                    nuevos2["fecha"] = pd.to_datetime(nuevos2["fecha"], errors="coerce").dt.strftime("%Y-%m-%d")
                                    vals = nuevos2[["numero","nombre","equipo","fecha","tipo"]].astype(str).values.tolist()
                                    start_row = max(2, len(ws.get_all_values()) + 1)
                                    ws.update(f"A{start_row}", vals)
                                    clear_cache()
                                    st.success(f"Importados {len(nuevos)} registros.")
                            else:
                                replace_agenda_df(df_norm[["numero","nombre","equipo","fecha","tipo"]])
                                clear_cache()
                                st.success(f"Reemplazo completo realizado: {len(df_norm)} registros.")
                except Exception as e:
                    st.error(f"Error importando: {e}")
            else:
                st.info("Selecciona un archivo para importar.")

        else:
            st.markdown("### Diagnóstico")
            has_sa = "gcp_service_account" in st.secrets
            sheet_url = st.secrets.get("sheet_url") or (st.secrets.get("gcp_service_account", {}).get("sheet_url") if has_sa else None)
            st.write(f"**Secrets:** SA={'OK' if has_sa else 'FALTA'} | sheet_url={'OK' if sheet_url else 'FALTA'}")
            emp_df = get_empleados_df()
            ag_df = load_agenda_df()
            st.write(f"**Empleados cargados:** {len(emp_df)}")
            st.write(f"**Registros en agenda:** {0 if ag_df is None else len(ag_df)}")
            if not emp_df.empty:
                st.dataframe(emp_df.head(10), use_container_width=True)
            if ag_df is not None and not ag_df.empty:
                tmp = ag_df.copy()
                tmp["fecha"] = pd.to_datetime(tmp["fecha"], errors="coerce").dt.strftime("%Y-%m-%d")
                st.dataframe(tmp.head(10), use_container_width=True)

# ---------------- Reportes ----------------
with tab4:
    st.subheader("Reportes mensuales por equipo")
    df_all = load_agenda_df().copy()
    if df_all.empty:
        st.info("No hay registros para generar reportes.")
    else:
        df_all["anio"] = df_all["fecha"].dt.year
        df_all["mes"] = df_all["fecha"].dt.month
        hoy = dt.date.today()
        c1, c2 = st.columns(2)
        with c1:
            anioR = st.number_input("Año", value=hoy.year, min_value=hoy.year-3, max_value=hoy.year+3, step=1, key="anio_rep")
        with c2:
            mesR = st.selectbox("Mes", list(range(1,13)), index=hoy.month-1, format_func=lambda m: MESES[m-1], key="mes_rep")

        df_mes = df_all[(df_all["anio"]==int(anioR)) & (df_all["mes"]==int(mesR))].copy()
        if df_mes.empty:
            st.warning("No hay datos en el mes seleccionado.")
        else:
            pivot = pd.crosstab(df_mes["equipo"], df_mes["tipo"]).astype(int)
            pivot = pivot.reindex(columns=["Vacaciones","Permiso","Sanción"], fill_value=0)
            pivot["Total"] = pivot.sum(axis=1)
            pivot = pivot.sort_values("Total", ascending=False)

            st.markdown("**Resumen por equipo**")
            st.dataframe(pivot, use_container_width=True)
            st.bar_chart(pivot["Total"])

            dcnt = df_mes.groupby(df_mes["fecha"].dt.date)["numero"].count().reset_index(name="registros")
            criticos = dcnt[dcnt["registros"]>=3].sort_values(["registros","fecha"], ascending=[False, True])
            st.markdown("**Días críticos (3 o más registros en el día)**")
            if criticos.empty:
                st.info("No hubo días críticos en este mes.")
            else:
                st.dataframe(criticos.rename(columns={"fecha":"día"}), use_container_width=True)

            excel_io = BytesIO()
            with pd.ExcelWriter(excel_io, engine="xlsxwriter") as writer:
                pivot.to_excel(writer, sheet_name="Resumen_Equipos")
                dcnt.to_excel(writer, sheet_name="Conteo_por_Dia", index=False)
                if not criticos.empty:
                    criticos.rename(columns={"fecha":"dia"}).to_excel(writer, sheet_name="Dias_Criticos", index=False)

            st.download_button(
                "⬇️ Descargar Excel del reporte",
                data=excel_io.getvalue(),
                file_name=f"reporte_{int(anioR)}_{int(mesR):02d}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="dl_rep_xlsx"
            )

            st.download_button(
                "⬇️ Descargar CSV (Resumen por equipo)",
                data=pivot.to_csv().encode("utf-8"),
                file_name=f"reporte_equipos_{int(anioR)}_{int(mesR):02d}.csv",
                mime="text/csv",
                key="dl_rep_csv"
            )
