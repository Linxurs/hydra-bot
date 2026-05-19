import os

from google import genai


def listar_modelos():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("❌ Error: No se encuentra la variable de entorno GEMINI_API_KEY")
        return

    client = genai.Client(api_key=api_key)
    print("🔍 Listando modelos disponibles en tu API:")
    print("-" * 50)

    # La nueva API permite iterar sobre los modelos directamente
    for model in client.models.list():
        print(f"🤖 Modelo: {model.name}")
        print(f"   > Soporta: {model.supported_actions}")
        print("-" * 50)


if __name__ == "__main__":
    listar_modelos()
