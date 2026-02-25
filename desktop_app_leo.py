import os
import sys
import time
import threading
import urllib.request
import webview

# ✅ Paso extra muy importante (ruta correcta en .exe y en desarrollo)
if getattr(sys, 'frozen', False):
    os.chdir(os.path.dirname(sys.executable))
else:
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

HOST = "127.0.0.1"
PORT = "8000"
URL = f"http://{HOST}:{PORT}/"

def wait_for_server(url: str, timeout: float = 10.0, interval: float = 0.2) -> bool:
    """Espera hasta que el servidor responda (o hasta timeout)."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except Exception:
            time.sleep(interval)
    return False

def run_django():
    """
    Arranca el servidor de Django en segundo plano.
    --noreload es CLAVE para que no cree procesos duplicados.
    """
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "escovol.settings")
    from django.core.management import execute_from_command_line
    execute_from_command_line([
        "manage.py",
        "runserver",
        f"{HOST}:{PORT}",
        "--noreload",
    ])

def start_app():
    threading.Thread(target=run_django, daemon=True).start()

    # Esperar a que Django esté listo (mejor que sleep fijo)
    wait_for_server(URL, timeout=12.0)

    webview.create_window(
        title="Sistema Escuela de Voleibol",
        url=URL,
        width=1200,
        height=800,
        resizable=True,
    )
    webview.start()

if __name__ == "__main__":
    start_app()
