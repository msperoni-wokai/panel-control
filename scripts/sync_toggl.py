#!/usr/bin/env python3
"""Sincroniza horas, clientes y proyectos de Toggl Track hacia data/toggl.json
del repo panel-control y lo publica en GitHub Pages. Reemplaza la scheduled
task de Claude "sincronizar-toggl-panel" (sin LLM: es ETL determinista).

Programado vía launchd: ~/Library/LaunchAgents/com.wokai.sync-toggl.plist
Log: ~/.claude/woka-panel/scripts/sync_toggl.log
"""
import base64
import datetime
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

WORKSPACE = "21523671"
TOKEN_FILE = Path.home() / ".config/toggl/token"
REPO = Path.home() / ".claude/woka-panel"
OUT = REPO / "data/toggl.json"
DESDE = "2026-07-01"


def api(url, payload=None):
    token = TOKEN_FILE.read_text().strip()
    auth = base64.b64encode(f"{token}:api_token".encode()).decode()
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={
        "Authorization": f"Basic {auth}",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def main():
    hoy = datetime.datetime.now().strftime("%Y-%m-%d")  # hora local (Argentina)

    clientes = api(f"https://api.track.toggl.com/api/v9/workspaces/{WORKSPACE}/clients") or []
    proyectos = api(f"https://api.track.toggl.com/api/v9/workspaces/{WORKSPACE}/projects") or []
    resumen = api(
        f"https://api.track.toggl.com/reports/api/v3/workspace/{WORKSPACE}/summary/time_entries",
        {"start_date": DESDE, "end_date": hoy, "grouping": "projects"},
    )

    cliente_por_id = {c["id"]: c["name"] for c in clientes}
    proyecto_por_id = {p["id"]: p for p in proyectos}

    horas = {}
    for g in resumen.get("groups", []):
        pid = g.get("id")
        segundos = sum(s.get("seconds", 0) for s in g.get("sub_groups", [])) or g.get("seconds", 0)
        nombre = proyecto_por_id[pid]["name"] if pid in proyecto_por_id else "Sin proyecto"
        horas[nombre] = horas.get(nombre, 0) + round(segundos / 3600, 1)
    horas = {k: round(v, 1) for k, v in horas.items()}

    catalogo = {
        "clientes": sorted(cliente_por_id.values()),
        "proyectos": {
            p["name"]: cliente_por_id.get(p.get("client_id"), "")
            for p in proyectos
        },
    }

    nuevo = {"fecha": hoy, "horas": horas, "catalogo": catalogo}

    OUT.parent.mkdir(parents=True, exist_ok=True)
    previo = json.loads(OUT.read_text()) if OUT.exists() else None
    if previo == nuevo:
        print(f"{hoy}: sin cambios, no se publica.")
        return 0

    OUT.write_text(json.dumps(nuevo, ensure_ascii=False, indent=1) + "\n")

    for cmd in (
        ["git", "add", "data/toggl.json"],
        ["git", "commit", "-m", f"Toggl {hoy} (sync automático)"],
        ["git", "push"],
    ):
        r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"ERROR en {' '.join(cmd)}: {r.stderr.strip()}", file=sys.stderr)
            return 1

    total = round(sum(horas.values()), 1)
    print(f"{hoy}: {len(horas)} proyectos, {total} h desde {DESDE} — publicado.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # que el log siempre diga qué pasó
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
