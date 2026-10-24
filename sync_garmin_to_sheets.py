"""Sincroniza datos de Garmin Connect con la hoja Plan_Epic_2027.

Rellena, en las pestañas "Sem N", las columnas "Sueño (h)", "FC media" y
"Peso (kg)" de los últimos DAYS_BACK días. RPE, dolor de Aquiles, notas y
"¿Hecho?" no se tocan (son manuales).

Variables de entorno:
    SHEET_ID            ID de la hoja de Google
    GOOGLE_SA_JSON      JSON de la cuenta de servicio (contenido completo)
    GARMIN_TOKENS_B64   salida de get_garmin_token.py
    DAYS_BACK           opcional, por defecto 3
"""
import base64
import io
import json
import os
import tarfile
import tempfile
from datetime import date, datetime, timedelta

import gspread
from garminconnect import Garmin
from gspread.utils import rowcol_to_a1

SHEET_ID = os.environ["SHEET_ID"]
DAYS_BACK = int(os.environ.get("DAYS_BACK", "3"))
HEADER_ROW = 5          # fila de cabeceras en cada pestaña "Sem N"
FIRST_DAY_ROW = 6       # fila del lunes
COLS = {"Sueño (h)": "sueno", "FC media": "fc", "Peso (kg)": "peso",
        "RPE (1-10)": "rpe"}


def garmin_client() -> Garmin:
    tmp = tempfile.mkdtemp()
    raw = base64.b64decode(os.environ["GARMIN_TOKENS_B64"])
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        tar.extractall(tmp, filter="data")
    api = Garmin()
    api.login(tmp)
    return api


def activity_rpe(api: Garmin, act: dict):
    """RPE (1-10) de una actividad, o None si no lo registraste en el reloj.

    Garmin lo guarda en escala 0-100 en pasos de 10 (50 = RPE 5). Si el campo
    no viene en el listado, se consulta el detalle de la actividad.
    """
    raw = act.get("directWorkoutRpe")
    if raw is None:
        try:
            det = api.get_activity(act["activityId"]) or {}
            raw = (det.get("summaryDTO") or {}).get("directWorkoutRpe")
            if raw is None:
                raw = det.get("directWorkoutRpe")
        except Exception as e:
            print(f"  RPE detalle {act.get('activityId')}: {e}")
    print(f"  actividad {act.get('activityId')} "
          f"({(act.get('activityType') or {}).get('typeKey')}): RPE bruto={raw}")
    if not raw:
        return None
    return max(1, min(10, round(raw / 10)))


def day_metrics(api: Garmin, d: date) -> dict:
    ds = d.isoformat()
    out = {}

    try:  # horas de sueño de la noche que termina ese día
        sleep = (api.get_sleep_data(ds) or {}).get("dailySleepDTO") or {}
        secs = sleep.get("sleepTimeSeconds")
        if secs:
            out["sueno"] = round(secs / 3600, 1)
    except Exception as e:
        print(f"  [{ds}] sueño: {e}")

    try:  # actividades del día: FC media y RPE
        acts = api.get_activities_by_date(ds, ds) or []

        # FC media del día = media ponderada por duración
        pairs = [(a["averageHR"], a.get("duration") or 0)
                 for a in acts if a.get("averageHR")]
        total = sum(w for _, w in pairs)
        if total:
            out["fc"] = round(sum(h * w for h, w in pairs) / total)

        # RPE: si hay varias actividades, se queda con la más dura del día
        rpes = [r for r in (activity_rpe(api, a) for a in acts) if r]
        if rpes:
            out["rpe"] = max(rpes)
    except Exception as e:
        print(f"  [{ds}] actividades: {e}")

    try:  # peso (Garmin lo devuelve en gramos)
        comp = api.get_body_composition(ds) or {}
        lst = comp.get("dateWeightList") or []
        if lst and lst[0].get("weight"):
            out["peso"] = round(lst[0]["weight"] / 1000, 1)
    except Exception as e:
        print(f"  [{ds}] peso: {e}")

    return out


def parse_date(v) -> date:
    if isinstance(v, (int, float)):  # número de serie de Sheets
        return date(1899, 12, 30) + timedelta(days=int(v))
    return datetime.strptime(str(v).strip(), "%d/%m/%Y").date()


def main() -> None:
    api = garmin_client()
    gc = gspread.service_account_from_dict(json.loads(os.environ["GOOGLE_SA_JSON"]))
    sh = gc.open_by_key(SHEET_ID)

    today = date.today()
    days = [today - timedelta(days=i) for i in range(DAYS_BACK)]
    metrics = {d: day_metrics(api, d) for d in days}
    print({d.isoformat(): m for d, m in metrics.items()})

    for ws in sh.worksheets():
        if not ws.title.startswith("Sem "):
            continue
        try:
            monday = parse_date(
                ws.acell("B3", value_render_option="UNFORMATTED_VALUE").value
            )
        except Exception as e:
            print(f"{ws.title}: no se pudo leer el lunes ({e})")
            continue

        header = ws.row_values(HEADER_ROW)
        col_idx = {key: header.index(name) + 1
                   for name, key in COLS.items() if name in header}

        updates = []
        for d, m in metrics.items():
            off = (d - monday).days
            if not 0 <= off <= 6:
                continue
            row = FIRST_DAY_ROW + off
            for key, col in col_idx.items():
                if key in m:
                    updates.append({"range": rowcol_to_a1(row, col),
                                    "values": [[m[key]]]})
        if updates:
            ws.batch_update(updates, value_input_option="USER_ENTERED")
            print(f"{ws.title}: {len(updates)} celdas actualizadas")


if __name__ == "__main__":
    main()
