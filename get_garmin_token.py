"""Ejecutar UNA sola vez en tu PC.

Inicia sesión en Garmin (con MFA si lo tienes) y imprime un texto en base64
con los tokens. Ese texto se guarda como secreto GARMIN_TOKENS_B64 en GitHub,
así el job en la nube no necesita tu contraseña.

Uso:
    pip install garminconnect
    python get_garmin_token.py
"""
import base64
import getpass
import io
import tarfile
from pathlib import Path

from garminconnect import Garmin

store = Path.home() / ".garminconnect_sync"
store.mkdir(exist_ok=True)

email = input("Email de Garmin: ").strip()
password = getpass.getpass("Contraseña de Garmin: ")

api = Garmin(email, password, prompt_mfa=lambda: input("Código MFA: ").strip())
api.login(str(store))  # guarda los tokens en la carpeta

buf = io.BytesIO()
with tarfile.open(fileobj=buf, mode="w:gz") as tar:
    for f in store.iterdir():
        tar.add(f, arcname=f.name)

print("\n--- Copia TODO lo siguiente como secreto GARMIN_TOKENS_B64 ---\n")
print(base64.b64encode(buf.getvalue()).decode())
print("\n--- Fin ---")
