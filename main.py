import os
import shutil
import uuid
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client
from extractor import extract_invoice_data
from pathlib import Path
from dotenv import load_dotenv
import traceback

import re
from datetime import datetime

MONTHS_ES = {
    "ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5, "JUNIO": 6,
    "JULIO": 7, "AGOSTO": 8, "SEPTIEMBRE": 9, "SETIEMBRE": 9, "OCTUBRE": 10,
    "NOVIEMBRE": 11, "DICIEMBRE": 12
}

def normalize_date_es(raw: str | None) -> str | None:
    if not raw:
        return None
    s = raw.strip().upper()
    m = re.match(r"^(\d{1,2})/([A-ZÁÉÍÓÚÑ]+)/(\d{4})$", s)
    if m:
        d, mon, y = m.groups()
        mon = (mon.replace("Á", "A").replace("É", "E")
               .replace("Í", "I").replace("Ó", "O").replace("Ú", "U"))
        mm = MONTHS_ES.get(mon)
        if not mm:
            return None
        return f"{int(y):04d}-{mm:02d}-{int(d):02d}"
    try:
        return datetime.fromisoformat(s).date().isoformat()
    except Exception:
        return None

def normalize_time(raw: str | None) -> str | None:
    if not raw:
        return None
    s = raw.strip().upper().replace(".", "")
    try:
        return datetime.strptime(s, "%I:%M %p").strftime("%H:%M:%S")
    except Exception:
        return None

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=True)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
BUCKET_NAME = os.getenv("SUPABASE_BUCKET", "invoices_bucket")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Faltan SUPABASE_URL o SUPABASE_KEY en .env")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI(title="API Asistencia")

origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://proyecto-facturas.vercel.app",
    "https://automatizacion-de-escaneo-doc-front.vercel.app",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AttendanceUpdate(BaseModel):
    worker_name: str | None = None
    dni: str | None = None
    date: str | None = None
    entry_time: str | None = None
    exit_time: str | None = None
    shift: str | None = None
    signature_present: bool | None = None
    is_free_day: bool | None = None
    free_day_note: str | None = None



@app.get("/")
def health_check():
    return {"status": "online", "message": "Backend listo"}


@app.get("/attendance")
def get_attendance():
    try:
        response = (
            supabase.table("attendance")
            .select("*")
            .order("created_at", desc=True)
            .execute()
        )
        return response.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listando asistencia: {str(e)}")


# Alias para tu frontend actual (App.jsx usa /invoices)
@app.get("/invoices")
def get_invoices_alias():
    return get_attendance()


@app.put("/attendance/{record_id}")
def update_attendance(record_id: str, item: AttendanceUpdate):
    try:
        update_data = {k: v for k, v in item.model_dump().items() if v is not None}
        if not update_data:
            raise HTTPException(status_code=400, detail="No se enviaron datos para actualizar")

        result = (
            supabase.table("attendance")
            .update(update_data)
            .eq("id", record_id)
            .execute()
        )
        return {"status": "success", "data": result.data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error actualizando asistencia: {str(e)}")


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    temp_filename = f"temp_{uuid.uuid4()}.pdf"

    try:
        if file.content_type != "application/pdf":
            raise HTTPException(status_code=400, detail="Solo se aceptan PDFs.")

        with open(temp_filename, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        data_extracted = extract_invoice_data(temp_filename)
        print("EXTRACTED:", data_extracted)
        print("BUCKET:", BUCKET_NAME)

        if "error" in data_extracted:
            raise HTTPException(
                status_code=data_extracted.get("status_code", 422),
                detail=data_extracted["error"],
            )

        storage_filename = f"{uuid.uuid4()}.pdf"
        with open(temp_filename, "rb") as f:
            supabase.storage.from_(BUCKET_NAME).upload(
                path=storage_filename,
                file=f,
                file_options={"content-type": "application/pdf"},
            )

        public_url = supabase.storage.from_(BUCKET_NAME).get_public_url(storage_filename)
        records = data_extracted.get("records", [])

        inserted = 0
        for record in records:
            payload = {
                "worker_name": record.get("worker_name"),
                "dni": record.get("dni"),
                "date": normalize_date_es(record.get("date")),
                "entry_time": normalize_time(record.get("entry_time")),
                "exit_time": normalize_time(record.get("exit_time")),
                "shift": record.get("shift"),
                "signature_present": record.get("signature_present"),
                "is_free_day": record.get("is_free_day", False),
                "free_day_note": record.get("free_day_note", ""),
                "file_url": public_url,
            }


            supabase.table("attendance").insert(payload).execute()
            inserted += 1

        return {"status": "success", "records_saved": inserted}

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error en upload: {str(e)}")
    finally:
        if os.path.exists(temp_filename):
            os.remove(temp_filename)

# ---- EJECUTAR SERVIDOR ----
import uvicorn

if __name__ == "__main__":
    uvicorn.run("main:app", reload=True)