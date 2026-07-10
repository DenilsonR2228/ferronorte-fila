#!/usr/bin/env python3
"""
Ferronorte Industrial - Servidor Fila de Motoristas
Hospedagem: Render.com  |  Banco: Supabase
"""

import json
import os
import time
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

PORT = int(os.environ.get("PORT", 8000))
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# Cache local para evitar leituras desnecessarias no banco
_cache = {"dados": None, "ts": 0}
CACHE_TTL = 2  # segundos


def supabase_req(method, path, body=None):
    url = SUPABASE_URL.rstrip("/") + path
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("apikey", SUPABASE_KEY)
    req.add_header("Authorization", "Bearer " + SUPABASE_KEY)
    req.add_header("Content-Type", "application/json")
    req.add_header("Prefer", "return=representation")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


def carregar_dados():
    now = time.time()
    if _cache["dados"] and now - _cache["ts"] < CACHE_TTL:
        return _cache["dados"]
    try:
        rows = supabase_req("GET", "/rest/v1/fila_dados?select=*&order=id.desc&limit=1")
        if rows:
            dados = json.loads(rows[0]["conteudo"])
            dados["_row_id"] = rows[0]["id"]
        else:
            dados = {"fila": [], "cargas": [], "ultima_atualizacao": 0, "_row_id": None}
    except Exception as e:
        print(f"Erro ao carregar dados: {e}")
        dados = _cache["dados"] or {"fila": [], "cargas": [], "ultima_atualizacao": 0, "_row_id": None}
    _cache["dados"] = dados
    _cache["ts"] = now
    return dados


def salvar_dados(dados):
    dados["ultima_atualizacao"] = time.time()
    row_id = dados.pop("_row_id", None)
    conteudo = json.dumps(dados, ensure_ascii=False)
    dados["_row_id"] = row_id
    try:
        if row_id:
            supabase_req("PATCH", f"/rest/v1/fila_dados?id=eq.{row_id}", {"conteudo": conteudo})
        else:
            res = supabase_req("POST", "/rest/v1/fila_dados", {"conteudo": conteudo})
            dados["_row_id"] = res[0]["id"] if res else None
    except Exception as e:
        print(f"Erro ao salvar dados: {e}")
    _cache["dados"] = dados
    _cache["ts"] = time.time()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {args[0]} {args[1]}")

    def cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(200)
        self.cors()
        self.end_headers()

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.serve_file("app.html", "text/html")
        elif self.path in ("/treino", "/treino.html"):
            self.serve_file("treino.html", "text/html")
        elif self.path == "/api/dados":
            self.send_json(carregar_dados())
        elif self.path.startswith("/api/poll"):
            desde = 0
            if "since=" in self.path:
                try:
                    desde = float(self.path.split("since=")[1])
                except:
                    pass
            deadline = time.time() + 20
            while time.time() < deadline:
                _cache["ts"] = 0  # forca releitura
                d = carregar_dados()
                if d.get("ultima_atualizacao", 0) > desde:
                    self.send_json(d)
                    return
                time.sleep(1.5)
            self.send_json({"sem_mudanca": True})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length))
        except:
            self.send_response(400)
            self.end_headers()
            return

        dados = carregar_dados()

        if self.path == "/api/motorista":
            dados["fila"].append(payload)
            salvar_dados(dados)
            self.send_json({"ok": True, "dados": dados})

        elif self.path == "/api/status":
            for m in dados["fila"]:
                if m["id"] == payload.get("id"):
                    m["status"] = payload.get("status")
                    break
            salvar_dados(dados)
            self.send_json({"ok": True})

        elif self.path == "/api/carga":
            dados["cargas"].append(payload)
            salvar_dados(dados)
            self.send_json({"ok": True, "dados": dados})

        elif self.path == "/api/remover_carga":
            dados["cargas"] = [c for c in dados["cargas"] if c["id"] != payload.get("id")]
            salvar_dados(dados)
            self.send_json({"ok": True})

        elif self.path == "/api/limpar":
            dados["fila"] = []
            salvar_dados(dados)
            self.send_json({"ok": True})

        else:
            self.send_response(404)
            self.end_headers()

    def serve_file(self, filename, content_type):
        if not os.path.exists(filename):
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"app.html nao encontrado.")
            return
        with open(filename, "rb") as f:
            content = f.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", len(content))
        self.cors()
        self.end_headers()
        self.wfile.write(content)

    def send_json(self, data):
        # Remove _row_id interno antes de enviar ao cliente
        clean = {k: v for k, v in data.items() if k != "_row_id"}
        content = json.dumps(clean, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(content))
        self.cors()
        self.end_headers()
        self.wfile.write(content)


if __name__ == "__main__":
    print(f"Servidor iniciando na porta {PORT}...")
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("AVISO: Variaveis SUPABASE_URL e SUPABASE_KEY nao configuradas!")
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    server.serve_forever()
