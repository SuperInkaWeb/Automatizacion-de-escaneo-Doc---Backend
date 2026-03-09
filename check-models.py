from google import genai
import os
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("❌ No se encontró la API KEY")
else:
    try:
        client = genai.Client(api_key=api_key)

        print("🔍 Buscando modelos disponibles...")

        for model in client.models.list():
            print(" -", model.name)

    except Exception as e:
        print("❌ Error conectando:", e)