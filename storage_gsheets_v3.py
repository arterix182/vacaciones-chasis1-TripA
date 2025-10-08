# (archivo) storage_gsheets_v3.py — validación en servidor
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from gspread.exceptions import WorksheetNotFound, GSpreadException
import pandas as pd

SCOPE = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

EMP_HEADERS = ["numero","nombre","equipo"]
AGENDA_HEADERS = ["numero","nombre","equipo","fecha","tipo"]

def _client():
    if "gcp_service_account" not in st.secrets:
        st.error("Faltan credenciales: agrega el bloque [gcp_service_account] en Settings → Secrets.")
        st.stop()

    info = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(info, scopes=SCOPE)
    gc = gspread.authorize(creds)

    sheet_url = st.secrets.get("sheet_url") or info.get("sheet_url")
    if not sheet_url:
        st.error("Falta 'sheet_url' en Secrets (al nivel raíz o dentro de [gcp_service_account]).")
        st.stop()

    try:
        sh = gc.open_by_url(sheet_url)
        return sh
    except Exception as e:
        st.error(f"No pude abrir el Google Sheet. Revisa 'sheet_url' y permisos. Detalle: {e}")
        st.stop()

def _ensure_headers(ws, expected_headers):
    try:
        first = ws.row_values(1)
    except Exception:
        first = []

    if not first:
        ws.update(f"A1:{chr(64+len(expected_headers))}1", [expected_headers])
        return

    norm_first = [c.strip().lower() for c in first]
    norm_expected = [c.strip().lower() for c in expected_headers]
    if norm_first[:len(norm_expected)] == norm_expected:
        return

    try:
        ws.insert_row(expected_headers, index=1)
    except Exception:
        ws.update(f"A1:{chr(64+len(expected_headers))}1", [expected_headers])

def _ws(name: str, expected_headers):
    sh = _client()
    try:
        ws = sh.worksheet(name)
    except WorksheetNotFound:
        ws = sh.add_worksheet(title=name, rows=4000, cols=16)
    _ensure_headers(ws, expected_headers)
    return ws

def get_empleados_df() -> pd.DataFrame:
    ws = _ws("empleados", EMP_HEADERS)
    try:
        rows = ws.get_all_records()
    except GSpreadException:
        _ensure_headers(ws, EMP_HEADERS)
        values = ws.get_all_values()
        if not values or len(values) <= 1:
            return pd.DataFrame(columns=EMP_HEADERS)
        rows = [dict(zip(EMP_HEADERS, r + [""]*(len(EMP_HEADERS)-len(r)))) for r in values[1:]]
    if not rows:
        return pd.DataFrame(columns=EMP_HEADERS)
    df = pd.DataFrame(rows, columns=EMP_HEADERS)
    df["numero"] = df["numero"].astype(str).str.strip()
    df["nombre"] = df["nombre"].astype(str).str.strip()
    df["equipo"] = df["equipo"].astype(str).str.strip()
    return df

def get_empleados_dict() -> dict:
    df = get_empleados_df()
    d = {}
    for _, r in df.iterrows():
        num = str(r["numero"]).strip()
        if not num:
            continue
        d[num] = {"nombre": r["nombre"], "equipo": r["equipo"]}
        num_nz = num.lstrip("0")
        if num_nz and num_nz != num and num_nz not in d:
            d[num_nz] = {"nombre": r["nombre"], "equipo": r["equipo"]}
    return d

def _agenda_df_fresh() -> pd.DataFrame:
    ws = _ws("agenda", AGENDA_HEADERS)
    try:
        rows = ws.get_all_records()
    except GSpreadException:
        _ensure_headers(ws, AGENDA_HEADERS)
        values = ws.get_all_values()
        if not values or len(values) <= 1:
            return pd.DataFrame(columns=AGENDA_HEADERS)
        rows = [dict(zip(AGENDA_HEADERS, r + [""]*(len(AGENDA_HEADERS)-len(r)))) for r in values[1:]]
    if not rows:
        return pd.DataFrame(columns=AGENDA_HEADERS)
    df = pd.DataFrame(rows, columns=AGENDA_HEADERS)
    df["numero"] = df["numero"].astype(str).str.strip()
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    df = df.dropna(subset=["fecha"])
    df["equipo"] = df["equipo"].astype(str).str.strip()
    return df

def get_agenda_df() -> pd.DataFrame:
    return _agenda_df_fresh()

def append_agenda_row_safe(rec: dict):
    ws = _ws("agenda", AGENDA_HEADERS)
    df = _agenda_df_fresh()
    try:
        fecha = pd.to_datetime(rec.get("fecha"), errors="coerce").date()
    except Exception:
        raise ValueError("FORMATO_FECHA")
    if pd.isna(fecha):
        raise ValueError("FORMATO_FECHA")

    equipo = str(rec.get("equipo","")).strip()
    mismos = df[df["fecha"].dt.date == fecha]
    if len(mismos) >= 3:
        raise ValueError("LLENO")
    if any(mismos["equipo"] == equipo):
        raise ValueError("MISMO_EQUIPO")

    values = [[
        str(rec.get("numero","")).strip(),
        str(rec.get("nombre","")).strip(),
        equipo,
        fecha.isoformat(),
        str(rec.get("tipo","")).strip()
    ]]
    current_rows = len(ws.get_all_values())
    start_row = max(2, current_rows + 1)
    ws.update(f"A{start_row}", values)

    df2 = _agenda_df_fresh()
    total = len(df2[df2["fecha"].dt.date == fecha])
    if total > 3:
        raise ValueError("RACE_CONDITION")

def replace_agenda_df(df: pd.DataFrame):
    ws = _ws("agenda", AGENDA_HEADERS)
    ws.clear()
    ws.update("A1:E1", [AGENDA_HEADERS])
    if df is None or df.empty:
        return
    df2 = df.copy()
    df2["fecha"] = pd.to_datetime(df2["fecha"], errors="coerce").dt.strftime("%Y-%m-%d")
    values = df2[AGENDA_HEADERS].astype(str).fillna("").values.tolist()
    ws.update("A2", values)

def append_empleados_rows(df: pd.DataFrame):
    ws = _ws("empleados", EMP_HEADERS)
    df2 = df.copy()
    df2 = df2[EMP_HEADERS].astype(str).fillna("")
    values = df2.values.tolist()
    if not values:
        return
    current_rows = len(ws.get_all_values())
    start_row = max(2, current_rows + 1)
    ws.update(f"A{start_row}", values)

def replace_empleados_df(df: pd.DataFrame):
    ws = _ws("empleados", EMP_HEADERS)
    ws.clear()
    ws.update("A1:C1", [EMP_HEADERS])
    if df is None or df.empty:
        return
    df2 = df.copy()
    df2 = df2[EMP_HEADERS].astype(str).fillna("")
    ws.update("A2", df2.values.tolist())
