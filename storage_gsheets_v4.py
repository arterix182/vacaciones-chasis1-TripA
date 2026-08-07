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
        st.error("Faltan credenciales: agrega [gcp_service_account] en Secrets.")
        st.stop()
    info = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(info, scopes=SCOPE)
    gc = gspread.authorize(creds)
    sheet_url = st.secrets.get("sheet_url") or info.get("sheet_url")
    if not sheet_url:
        st.error("Falta sheet_url en Secrets.")
        st.stop()
    try:
        return gc.open_by_url(sheet_url)
    except Exception as e:
        st.error(f"No pude abrir el Google Sheet. Revisa sheet_url y permisos. Detalle: {e}")
        st.stop()

def _ensure_headers(ws, headers):
    try:
        first = ws.row_values(1)
    except Exception:
        first = []
    if not first:
        end_col = chr(64 + len(headers))
        ws.update(f"A1:{end_col}1", [headers])
        return
    first_norm = [str(x).strip().lower() for x in first]
    headers_norm = [x.lower() for x in headers]
    if first_norm[:len(headers_norm)] != headers_norm:
        try:
            ws.insert_row(headers, index=1)
        except Exception:
            end_col = chr(64 + len(headers))
            ws.update(f"A1:{end_col}1", [headers])

def _ws(name, headers):
    sh = _client()
    try:
        ws = sh.worksheet(name)
    except WorksheetNotFound:
        ws = sh.add_worksheet(title=name, rows=5000, cols=20)
    _ensure_headers(ws, headers)
    return ws

def get_empleados_df():
    ws = _ws("empleados", EMP_HEADERS)
    try:
        rows = ws.get_all_records()
    except GSpreadException:
        vals = ws.get_all_values()
        if len(vals) <= 1:
            return pd.DataFrame(columns=EMP_HEADERS)
        rows = [dict(zip(EMP_HEADERS, r + [""]*(len(EMP_HEADERS)-len(r)))) for r in vals[1:]]
    if not rows:
        return pd.DataFrame(columns=EMP_HEADERS)
    df = pd.DataFrame(rows)
    for c in EMP_HEADERS:
        if c not in df.columns:
            df[c] = ""
    df = df[EMP_HEADERS].copy()
    for c in EMP_HEADERS:
        df[c] = df[c].astype(str).str.strip()
    return df

def get_empleados_dict():
    df = get_empleados_df()
    out = {}
    for _, r in df.iterrows():
        n = str(r["numero"]).strip()
        if not n:
            continue
        rec = {"nombre": r["nombre"], "equipo": r["equipo"]}
        out[n] = rec
        nz = n.lstrip("0")
        if nz and nz not in out:
            out[nz] = rec
    return out

def get_agenda_df():
    ws = _ws("agenda", AGENDA_HEADERS)
    try:
        rows = ws.get_all_records()
    except GSpreadException:
        vals = ws.get_all_values()
        if len(vals) <= 1:
            return pd.DataFrame(columns=AGENDA_HEADERS)
        rows = [dict(zip(AGENDA_HEADERS, r + [""]*(len(AGENDA_HEADERS)-len(r)))) for r in vals[1:]]
    if not rows:
        return pd.DataFrame(columns=AGENDA_HEADERS)
    df = pd.DataFrame(rows)
    for c in AGENDA_HEADERS:
        if c not in df.columns:
            df[c] = ""
    df = df[AGENDA_HEADERS].copy()
    df["numero"] = df["numero"].astype(str).str.strip()
    df["nombre"] = df["nombre"].astype(str).str.strip()
    df["equipo"] = df["equipo"].astype(str).str.strip()
    df["tipo"] = df["tipo"].astype(str).str.strip()
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    return df.dropna(subset=["fecha"])

def _append_record(rec):
    ws = _ws("agenda", AGENDA_HEADERS)
    fecha = pd.to_datetime(rec.get("fecha"), errors="coerce")
    if pd.isna(fecha):
        raise ValueError("FORMATO_FECHA")
    row = max(2, len(ws.get_all_values()) + 1)
    values = [[
        str(rec.get("numero","")).strip(),
        str(rec.get("nombre","")).strip(),
        str(rec.get("equipo","")).strip(),
        fecha.date().isoformat(),
        str(rec.get("tipo","")).strip(),
    ]]
    ws.update(f"A{row}", values)

def append_agenda_row_safe(rec):
    df = get_agenda_df()
    fecha = pd.to_datetime(rec.get("fecha"), errors="coerce")
    if pd.isna(fecha):
        raise ValueError("FORMATO_FECHA")
    f = fecha.date()
    equipo = str(rec.get("equipo","")).strip()
    mismos = df[df["fecha"].dt.date == f] if not df.empty else df.iloc[0:0]
    if len(mismos) >= 3:
        raise ValueError("LLENO")
    if not mismos.empty and any(mismos["equipo"].astype(str).str.strip() == equipo):
        raise ValueError("MISMO_EQUIPO")
    _append_record(rec)

def append_agenda_row_admin(rec):
    _append_record(rec)

def delete_agenda_rows(keys):
    df = get_agenda_df()
    if df.empty:
        return 0
    df["fecha_iso"] = df["fecha"].dt.strftime("%Y-%m-%d")
    mask = ~df.apply(lambda r: (str(r["numero"]), r["fecha_iso"], str(r["tipo"])) in keys, axis=1)
    kept = df[mask][AGENDA_HEADERS].copy()
    ws = _ws("agenda", AGENDA_HEADERS)
    ws.clear()
    ws.update("A1:E1", [AGENDA_HEADERS])
    if not kept.empty:
        kept["fecha"] = pd.to_datetime(kept["fecha"], errors="coerce").dt.strftime("%Y-%m-%d")
        ws.update("A2", kept[AGENDA_HEADERS].astype(str).values.tolist())
    return len(df) - len(kept)

def replace_empleados_df(df):
    ws = _ws("empleados", EMP_HEADERS)
    ws.clear()
    ws.update("A1:C1", [EMP_HEADERS])
    if df is None or df.empty:
        return
    ws.update("A2", df[EMP_HEADERS].astype(str).fillna("").values.tolist())

def append_empleados_rows(df):
    ws = _ws("empleados", EMP_HEADERS)
    out = df[EMP_HEADERS].astype(str).fillna("")
    if out.empty:
        return
    row = max(2, len(ws.get_all_values()) + 1)
    ws.update(f"A{row}", out.values.tolist())
