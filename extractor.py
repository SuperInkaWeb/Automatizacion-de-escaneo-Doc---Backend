from google import genai
import os
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=True)

api_key = os.getenv("GEMINI_API_KEY")
print("GEMINI DEBUG:", (api_key or "VACIO")[:12])  # temporal

if not api_key:
    raise ValueError("No se encontró GEMINI_API_KEY")

client = genai.Client(api_key=api_key)

def extract_invoice_data(pdf_path):
    prompt = """
Extrae la tabla de asistencia del documento.

Reglas OBLIGATORIAS:
1) Detecta mes y año desde PLANILLA (ej: ENERO 2025).
2) Para cada fila, construye "date" en formato YYYY-MM-DD usando:
   - día de la columna FECHA
   - mes/año de PLANILLA
3) Incluye filas si:
   - tienen al menos una marca (entry_time o exit_time o signature_present=true), O
   - el día está marcado explícitamente como libre/descanso (ej: "día(s) libre(s)", "descanso", línea diagonal anotada).
4) shift solo "D" o "N" cuando exista; si es día libre usar "".
5) HORAS (columas HORA ENTRADA y HORA SALIDA):
   - Lee grafías como: "8:Am", "8 AM", "8am", "08:00 am", "7:pm", "7 pm", "19:00".
   - Normaliza SIEMPRE a formato de salida "hh:mm AM/PM" con dos dígitos y espacio, por ejemplo:
     "08:00 AM", "07:00 PM". Nunca uses formato 24h en la salida.
   - Si no hay minutos escritos (ej. "8 AM"), asume ":00".
   - Si aparece "19:00" en formato 24h, conviértelo a "07:00 PM".
   - Si la celda está ilegible pero el turno es claro:
       • D (día)  -> entry_time="08:00 AM", exit_time="07:00 PM"
       • N (noche)-> entry_time="08:00 PM", exit_time="07:00 AM"
     Solo usa esta inferencia cuando falten horas y el turno sea inequívoco.
   - Si no se puede identificar turno ni horas, dejar entry_time="" y exit_time="".
6) Si una anotación de "días libres" cubre un rango (ej: del 1 al 7), crea un registro por cada fecha de ese rango.
7) Devuelve SOLO JSON válido.

Formato:
{
  "records": [
    {
      "worker_name": "",
      "dni": "",
      "date": "YYYY-MM-DD",
      "entry_time": "hh:mm AM/PM",
      "exit_time": "hh:mm AM/PM",
      "shift": "D",
      "signature_present": true,
      "is_free_day": false,
      "free_day_note": ""
    }
  ]
}
"""

    try:
        uploaded = client.files.upload(file=pdf_path)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[prompt, uploaded],
            config={"response_mime_type": "application/json"},
        )

        raw = (response.text or "").strip()
        if not raw:
            return {"error": "Gemini devolvió respuesta vacía", "status_code": 502}

        return json.loads(raw)

    except Exception as e:
        return {"error": str(e), "status_code": 422}
