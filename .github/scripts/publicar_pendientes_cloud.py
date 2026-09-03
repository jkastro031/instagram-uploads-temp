"""
Corre dentro de GitHub Actions (ver .github/workflows/publicar.yml).
Revisa cola.json en la raiz del repo y publica en Instagram lo que ya
vencio su fecha. Los archivos de video ya estan en el repo (carpeta media/),
asi que no hace falta subirlos: se arma la video_url directo con
raw.githubusercontent.com. Al publicar, borra el archivo local (el commit
posterior del workflow lo borra tambien del repo) y marca el item.
"""
import json
import os
import time
from datetime import datetime

import requests

GRAPH_VERSION = "v19.0"
REPO_OWNER = os.environ["REPO_OWNER"]
REPO_NAME = os.environ["REPO_NAME"]
BRANCH = os.environ.get("REPO_BRANCH", "main")
IG_USER_ID = os.environ["IG_USER_ID"]
ACCESS_TOKEN = os.environ["IG_ACCESS_TOKEN"]

COLA_FILE = "cola.json"
MAX_INTENTOS = 5


def cargar_cola():
    if not os.path.exists(COLA_FILE):
        return []
    with open(COLA_FILE, encoding="utf-8") as f:
        return json.load(f)


def guardar_cola(cola):
    with open(COLA_FILE, "w", encoding="utf-8") as f:
        json.dump(cola, f, indent=2, ensure_ascii=False)


def crear_contenedor(video_url, caption, media_type="REELS", share_to_feed=True):
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{IG_USER_ID}/media"
    data = {
        "access_token": ACCESS_TOKEN,
        "media_type": media_type,
        "video_url": video_url,
        "caption": caption[:2200],
    }
    if media_type == "REELS":
        data["share_to_feed"] = "true" if share_to_feed else "false"
    resp = requests.post(url, data=data, timeout=60)
    result = resp.json()
    if "error" in result:
        raise RuntimeError(f"Error de Instagram (crear contenedor): {result['error']}")
    return result["id"]


def esperar_contenedor(container_id, timeout=850, interval=10):
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{container_id}"
    elapsed = 0
    while elapsed < timeout:
        resp = requests.get(url, params={"fields": "status_code", "access_token": ACCESS_TOKEN}, timeout=30)
        resp.raise_for_status()
        status = resp.json().get("status_code")
        if status == "FINISHED":
            return True
        if status in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram no pudo procesar el video (status: {status})")
        print(f"  procesando... ({status})")
        time.sleep(interval)
        elapsed += interval
    raise RuntimeError("Timeout esperando que Instagram procese el video")


def publicar_contenedor(container_id):
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{IG_USER_ID}/media_publish"
    resp = requests.post(url, data={"access_token": ACCESS_TOKEN, "creation_id": container_id}, timeout=60)
    result = resp.json()
    if "error" in result:
        raise RuntimeError(f"Error de Instagram (publicar): {result['error']}")
    return result["id"]


def main():
    cola = cargar_cola()
    if not cola:
        print("Cola vacia, nada para publicar.")
        return

    ahora = datetime.now()
    publicados = 0

    for item in cola:
        if item.get("publicado") or item.get("error"):
            continue
        fecha = datetime.strptime(item["fecha"], "%Y-%m-%d %H:%M")
        if fecha > ahora:
            continue

        archivo = item["archivo"]
        print(f"\nPublicando {archivo} (programado para {item['fecha']})...")

        if not os.path.exists(archivo):
            print(f"  Error: no encuentro {archivo}")
            item["intentos"] = item.get("intentos", 0) + 1
        else:
            video_url = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/{BRANCH}/{archivo}"
            try:
                container_id = crear_contenedor(video_url, item.get("caption", ""), media_type=item.get("media_type", "REELS"))
                esperar_contenedor(container_id)
                media_id = publicar_contenedor(container_id)
                item["publicado"] = True
                item["media_id"] = media_id
                os.remove(archivo)
                print(f"  Publicado: {media_id}")
                publicados += 1
            except Exception as e:
                print(f"  Error: {e}")
                item["intentos"] = item.get("intentos", 0) + 1

        if item.get("intentos", 0) >= MAX_INTENTOS and not item.get("publicado"):
            item["error"] = True
            print(f"  Se supero el limite de intentos, queda marcado con error.")

        guardar_cola(cola)

    if publicados == 0:
        print("No habia nada vencido para publicar en esta corrida.")
    else:
        print(f"\n{publicados} publicacion(es) hecha(s) en esta corrida.")


if __name__ == "__main__":
    main()
