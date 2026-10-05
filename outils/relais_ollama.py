#!/usr/bin/env python3
"""Relais : parle « Ollama » sur 127.0.0.1:11434, sert par un llama-server LOCAL (par défaut 127.0.0.1:8095).

POUR LES DOCUMENTS RÉELS : le moteur doit être une instance À PART, sur 127.0.0.1 seulement, lancée avec
--no-slots et sans --log-file, sur un port qu'aucune autre machine ne peut joindre (8095 par défaut, hors
de tout canal ouvert vers la VM de développement). Exemple au bureau :
  llama-server -m <modèle.gguf> --host 127.0.0.1 --port 8095 --no-slots -c 16384 -ngl 99
Le relais REFUSE un amont qui n'est pas en 127.0.0.1 (ou localhost).

Pourquoi : le programme de hedrox appelle `ollama.Client('http://localhost:11434').chat()`.
Ce relais permet de le faire tourner SANS LE MODIFIER d'un octet et sans installer
Ollama — le moteur du poste (llama.socket, Gemma 4 12B, plafond VRAM tenu) repond.

CE QUE CA CHANGE PAR RAPPORT A SON MONTAGE, et qu'un resultat doit dire :
  - le MODELE : celui que sert llama.cpp (lu a /props), pas `gpt-oss:20b` ;
  - `num_ctx` est ignore (le contexte est celui de l'unite llama.service) ;
  - `temperature` est TRANSMISE telle quelle (0.6 dans son code) — sauf si
    --temperature force une valeur, pour un rejeu deterministe.
Chaque appel est journalise (journal-relais.jsonl) : tailles, duree, modele.
Le journal ne contient PAS les textes — seulement des comptes. Python systeme seul.

Usage : python3 relais_ollama.py [--temperature 0] [--port 11434]
"""
import argparse
import json
import time
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

AMONT = "http://127.0.0.1:8095"          # l'instance À PART (voir l'en-tête), changeable par --amont
JOURNAL = Path(__file__).resolve().parent / "journal-relais.jsonl"
ARGS = None


def modele_servi():
    try:
        with urllib.request.urlopen(AMONT + "/props", timeout=120) as r:
            p = json.load(r)
        return Path(p.get("model_path", "?")).name, p.get("build_info", "?")
    except Exception as e:                      # le dire, ne pas l'avaler
        return f"(props illisible : {e})", "?"


class Relais(BaseHTTPRequestHandler):
    def log_message(self, *a):                  # silence sur stderr, le journal suffit
        pass

    def _json(self, code, obj):
        corps = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def do_GET(self):
        if self.path.startswith("/api/tags"):
            return self._json(200, {"models": [{"name": modele_servi()[0]}]})
        self._json(200, {"relais": "ollama -> llama.cpp", "amont": AMONT})

    def do_POST(self):
        if not self.path.startswith("/api/chat"):
            return self._json(404, {"error": f"relais : {self.path} non pris en charge"})
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        opts = req.get("options") or {}
        temp = ARGS.temperature if ARGS.temperature is not None else opts.get("temperature", 0.8)
        charge = {"messages": req["messages"], "temperature": temp,
                  "max_tokens": 4096, "stream": False}
        t0 = time.time()
        try:
            r = urllib.request.Request(AMONT + "/v1/chat/completions",
                                       json.dumps(charge).encode(),
                                       {"Content-Type": "application/json"})
            with urllib.request.urlopen(r, timeout=900) as rep:
                d = json.load(rep)
        except Exception as e:
            self._trace(req, temp, t0, erreur=str(e))
            return self._json(500, {"error": f"relais : amont en echec : {e}"})
        msg = d["choices"][0]["message"]
        contenu = msg.get("content") or ""
        u = d.get("usage", {})
        self._trace(req, temp, t0, invite=u.get("prompt_tokens"), sortie=u.get("completion_tokens"),
                    vide=not contenu.strip(), raisonnement=bool(msg.get("reasoning_content")),
                    fin=d["choices"][0].get("finish_reason"))
        self._json(200, {
            "model": req.get("model", "?"),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "message": {"role": "assistant", "content": contenu},
            "done": True, "done_reason": "stop",
            "prompt_eval_count": u.get("prompt_tokens", 0),
            "eval_count": u.get("completion_tokens", 0),
        })

    def _trace(self, req, temp, t0, **k):
        ligne = {"quand": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                 "modele_demande": req.get("model"), "temperature": temp,
                 "car_invite": sum(len(m.get("content", "")) for m in req["messages"]),
                 "duree_s": round(time.time() - t0, 2), **k}
        with JOURNAL.open("a", encoding="utf-8") as f:
            f.write(json.dumps(ligne, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=11434)
    ap.add_argument("--temperature", type=float, default=None)
    ap.add_argument("--amont", default=AMONT, help="llama-server local (http://127.0.0.1:<port>)")
    ARGS = ap.parse_args()
    from urllib.parse import urlparse
    if urlparse(ARGS.amont).hostname not in ("127.0.0.1", "localhost"):
        raise SystemExit(f"amont refusé : {ARGS.amont} n'est pas local (127.0.0.1)")
    AMONT = ARGS.amont.rstrip("/")
    nom, build = modele_servi()
    print(f"relais ollama -> llama.cpp sur 127.0.0.1:{ARGS.port} · modele servi : {nom} · {build}"
          f" · temperature : {'celle du client' if ARGS.temperature is None else ARGS.temperature}",
          flush=True)
    ThreadingHTTPServer(("127.0.0.1", ARGS.port), Relais).serve_forever()
