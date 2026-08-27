"""Servidor local da interface web. Roda no Python do sistema.

    python servidor.py

Sobe um servidor em 127.0.0.1 numa porta livre e abre o navegador. Nada
sai da maquina: o endereco de loopback nao e alcancavel de fora.

Reaproveita nucleo.py inteiro. Nao importa bpy - conversa com o Blender
por subprocesso, igual a versao Tkinter.
"""

import json
import os
import queue
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import nucleo

AQUI = os.path.dirname(os.path.abspath(__file__))
PASTA_WEB = os.path.join(AQUI, "web")
PASTA_PROJETOS = os.path.join(AQUI, "projetos")

# Se a pagina parar de dar sinal de vida por esse tempo, o servidor se
# desliga. Evita processo pendurado quando a aba e fechada.
SEGUNDOS_SEM_SINAL = 45

# Carencia depois de um /api/sair. O navegador dispara 'pagehide' tambem
# num F5 ou numa navegacao, entao sair nao pode ser definitivo: se a
# pagina voltar dentro da carencia, o desligamento e cancelado.
GRACA_SAIDA = 8

TIPOS = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml",
         ".png": "image/png", ".ico": "image/x-icon"}


class Estado:
    def __init__(self):
        self.trava = threading.Lock()
        self.insp = None
        self.blend = None
        self.processo = None
        self.copias = []
        self.total = 0
        self.ouvintes = []
        self.historico = []
        self.ultimo_sinal = time.time()
        self.saindo_em = None
        self.desligando = False
        self.monitor = {"fonte": None, "backend": None, "nome": None,
                        "cpu_nome": None}

    def viva(self):
        """Cancela qualquer saida agendada. A pagina esta aqui."""
        self.ultimo_sinal = time.time()
        self.saindo_em = None

    # ------------------------------------------------------ eventos

    def inscrever(self):
        fila = queue.Queue()
        self.viva()
        with self.trava:
            self.ouvintes.append(fila)
            passado = list(self.historico)
        for linha in passado:
            fila.put(linha)
        return fila

    def desinscrever(self, fila):
        with self.trava:
            if fila in self.ouvintes:
                self.ouvintes.remove(fila)

    def publicar(self, tipo, dados, guardar=True):
        item = {"tipo": tipo, "dados": dados}
        with self.trava:
            if guardar:
                self.historico.append(item)
                del self.historico[:-400]
            ouvintes = list(self.ouvintes)
        for f in ouvintes:
            f.put(item)

    def tem_ouvinte(self):
        with self.trava:
            return bool(self.ouvintes)

    def limpar_historico(self):
        with self.trava:
            self.historico = []


ESTADO = Estado()


# ----------------------------------------------------------------- monitor
# O .blend guarda so 'GPU' ou 'CPU'. Qual placa e qual backend vem do
# hardware, entao a fonte do grafico e escolhida a partir do que a
# inspecao enumerou - a mesma ordem de preferencia do render.py.

FONTE_POR_BACKEND = {"OPTIX": "nvidia", "CUDA": "nvidia",
                     "HIP": "amd", "ONEAPI": "intel", "METAL": "metal"}


def definir_monitor(insp):
    disp = (insp or {}).get("dispositivos") or {}
    backend = disp.get("backend")
    fonte = FONTE_POR_BACKEND.get(backend)
    if fonte == "nvidia" and not shutil.which("nvidia-smi"):
        fonte = None
    if fonte in ("amd", "intel", "metal"):
        # sem ferramenta de linha de comando equivalente ao nvidia-smi
        fonte = None
    # 'cpu_nome' e nao 'cpu' de proposito: a amostra usa 'cpu' para a
    # porcentagem, e um update() com a mesma chave sobrescreveria o numero
    # pelo nome do processador.
    ESTADO.monitor = {
        "fonte": fonte,
        "backend": backend,
        "nome": disp.get("nome") if fonte else None,
        "cpu_nome": disp.get("cpu"),
    }
    return ESTADO.monitor


def _cpu_relogio():
    """Uso de CPU via GetSystemTimes. Instantaneo e sem dependencia."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class FILETIME(ctypes.Structure):
        _fields_ = [("baixo", wintypes.DWORD), ("alto", wintypes.DWORD)]

    ocioso, nucleo, usuario = FILETIME(), FILETIME(), FILETIME()
    ok = ctypes.windll.kernel32.GetSystemTimes(
        ctypes.byref(ocioso), ctypes.byref(nucleo), ctypes.byref(usuario))
    if not ok:
        return None
    junta = lambda f: (f.alto << 32) | f.baixo
    return junta(ocioso), junta(nucleo), junta(usuario)


CAMPOS_NVIDIA = "utilization.gpu,memory.used,memory.total,temperature.gpu"


def _amostra_nvidia():
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=" + CAMPOS_NVIDIA,
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
            startupinfo=nucleo.sem_janela())
    except Exception:
        return None
    linha = (r.stdout or "").strip().splitlines()
    if not linha:
        return None
    partes = [p.strip() for p in linha[0].split(",")]
    def num(i):
        try:
            return int(float(partes[i]))
        except (IndexError, ValueError):
            return None
    return {"gpu": num(0), "vram_usada": num(1), "vram_total": num(2),
            "temp": num(3)}


def monitorar():
    """Amostra a cada segundo, mas so enquanto alguem estiver ouvindo."""
    anterior = _cpu_relogio()
    while not ESTADO.desligando:
        time.sleep(1.0)
        if not ESTADO.tem_ouvinte():
            anterior = _cpu_relogio()
            continue

        agora = _cpu_relogio()
        cpu = None
        if anterior and agora:
            d_ocioso = agora[0] - anterior[0]
            d_total = (agora[1] - anterior[1]) + (agora[2] - anterior[2])
            if d_total > 0:
                cpu = max(0, min(100, round(100.0 * (1.0 - d_ocioso / d_total))))
        anterior = agora

        dados = {"cpu": cpu, "rodando": ESTADO.processo is not None}
        dados.update(ESTADO.monitor)
        if ESTADO.monitor.get("fonte") == "nvidia":
            leitura = _amostra_nvidia()
            if leitura:
                dados.update(leitura)
        ESTADO.publicar("monitor", dados, guardar=False)


# ------------------------------------------------------------------ render

def escolher_caminho(modo):
    try:
        r = subprocess.run([sys.executable, os.path.join(AQUI, "dialogo.py"), modo],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=300)
        return (r.stdout or "").strip()
    except Exception:
        return ""


def rodar_lote(cfg, plano, caminho_fila):
    try:
        cmd = nucleo.comando_render(cfg, caminho_fila)
    except Exception as e:
        ESTADO.publicar("erro", str(e))
        ESTADO.publicar("fim", {"feitos": 0})
        return

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace", bufsize=1,
        startupinfo=nucleo.sem_janela())
    ESTADO.processo = proc

    for linha in proc.stdout:
        if linha.startswith("LOTE|"):
            ESTADO.publicar("linha", linha[5:].strip())
    proc.wait()
    ESTADO.processo = None

    copiadas = 0
    for origem, destino in plano.get("copias", []):
        try:
            if os.path.exists(origem):
                pasta = os.path.dirname(destino)
                if pasta:
                    os.makedirs(pasta, exist_ok=True)
                shutil.copy2(origem, destino)
                copiadas += 1
        except Exception as e:
            ESTADO.publicar("linha", "FALHA ao copiar mascara: %s" % e)
    ESTADO.publicar("fim", {"copiadas": copiadas, "codigo": proc.returncode})


# ------------------------------------------------------------------ rotas

def api_inspecionar(corpo):
    blend = (corpo.get("blend") or "").strip()
    insp = nucleo.inspecionar(blend, (corpo.get("blender") or "").strip())
    ESTADO.insp = insp
    ESTADO.blend = blend
    insp["monitor"] = definir_monitor(insp)
    return insp


def _selecoes(corpo):
    cap = corpo.get("sel_capinha")
    cor = corpo.get("sel_corpo")
    return cap, cor


def api_plano(corpo):
    if ESTADO.insp is None:
        return {"erros": ["inspecione o .blend primeiro"], "avisos": [],
                "jobs": [], "copias": []}
    cfg = corpo["cfg"]
    erros, avisos = nucleo.conferir(cfg, ESTADO.insp)
    cap, cor = _selecoes(corpo)
    plano = nucleo.montar_fila(cfg, ESTADO.insp, sel_capinha=cap, sel_corpo=cor,
                               preview=bool(corpo.get("preview")),
                               forcar=bool(corpo.get("forcar")))
    jobs = [{"rotulo": j["rotulo"], "saida": j["saida"],
             "existe": os.path.exists(j["saida"]),
             "mascara": j.get("visiveis") is not None}
            for j in plano["jobs"]]
    return {"erros": erros, "avisos": avisos, "jobs": jobs,
            "copias": plano["copias"]}


def api_renderizar(corpo):
    if ESTADO.processo is not None:
        return {"ok": False, "motivo": "ja existe um lote rodando"}
    if ESTADO.insp is None:
        return {"ok": False, "motivo": "inspecione o .blend primeiro"}

    cfg = corpo["cfg"]
    erros, _ = nucleo.conferir(cfg, ESTADO.insp)
    if erros:
        return {"ok": False, "motivo": erros[0]}

    cap, cor = _selecoes(corpo)
    plano = nucleo.montar_fila(cfg, ESTADO.insp, sel_capinha=cap, sel_corpo=cor,
                               preview=bool(corpo.get("preview")),
                               forcar=bool(corpo.get("forcar")))
    if not plano["jobs"]:
        return {"ok": False, "motivo": "nada a fazer"}

    os.makedirs(PASTA_PROJETOS, exist_ok=True)
    caminho = os.path.join(PASTA_PROJETOS, "_fila.json")
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(plano, f, ensure_ascii=False, indent=1)

    ESTADO.limpar_historico()
    ESTADO.total = len(plano["jobs"])
    ESTADO.publicar("inicio", {"total": ESTADO.total,
                               "copias": len(plano["copias"])})
    threading.Thread(target=rodar_lote, args=(cfg, plano, caminho),
                     daemon=True).start()
    return {"ok": True, "total": ESTADO.total}


def api_parar(_corpo):
    if ESTADO.processo is not None:
        ESTADO.processo.terminate()
        ESTADO.publicar("linha", "interrompido pelo usuario")
        return {"ok": True}
    return {"ok": False, "motivo": "nada rodando"}


def api_projetos(_corpo):
    os.makedirs(PASTA_PROJETOS, exist_ok=True)
    nomes = sorted(f[:-5] for f in os.listdir(PASTA_PROJETOS)
                   if f.endswith(".json") and not f.startswith("_"))
    return {"projetos": nomes}


def api_abrir(corpo):
    nome = os.path.basename(corpo.get("nome") or "")
    caminho = os.path.join(PASTA_PROJETOS, nome + ".json")
    return {"cfg": nucleo.carregar_config(caminho)}


def api_salvar(corpo):
    nome = os.path.basename((corpo.get("nome") or "").strip())
    if not nome:
        return {"ok": False, "motivo": "dê um nome ao projeto"}
    cfg = json.loads(json.dumps(corpo["cfg"]))
    for g in cfg.get("grupos", {}).values():
        for var in g.get("variacoes", []):
            var.pop("_sel", None)
    nucleo.salvar_config(cfg, os.path.join(PASTA_PROJETOS, nome + ".json"))
    return {"ok": True, "nome": nome}


def api_escolher(corpo):
    return {"caminho": escolher_caminho(corpo.get("modo") or "pasta")}


def api_previa(corpo):
    cfg = corpo["cfg"]
    try:
        return {"caminho": nucleo.montar_caminho(
            cfg, corpo.get("capinha") or "capinha",
            corpo.get("camera") or "POS 1", corpo.get("numero") or "02")}
    except Exception as e:
        return {"erro": str(e)}


def api_sinal(_corpo):
    ESTADO.viva()
    return {"ok": True, "rodando": ESTADO.processo is not None}


def api_sair(_corpo):
    # 'pagehide' tambem dispara em F5 e navegacao, entao aqui so se agenda
    # a saida. Se a pagina voltar dentro da carencia, ESTADO.viva() cancela.
    ESTADO.saindo_em = time.time() + GRACA_SAIDA
    return {"ok": True, "em": GRACA_SAIDA}


ROTAS = {
    "/api/inspecionar": api_inspecionar,
    "/api/plano": api_plano,
    "/api/renderizar": api_renderizar,
    "/api/parar": api_parar,
    "/api/projetos": api_projetos,
    "/api/abrir": api_abrir,
    "/api/salvar": api_salvar,
    "/api/escolher": api_escolher,
    "/api/previa": api_previa,
    "/api/sinal": api_sinal,
    "/api/sair": api_sair,
}


# ---------------------------------------------------------------- handler

class Manipulador(BaseHTTPRequestHandler):
    server_version = "RenderDeLote/1.0"

    def log_message(self, *a):
        pass

    # ------------------------------------------------------- resposta

    def _json(self, dados, codigo=200):
        bruto = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(bruto)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(bruto)

    def _arquivo(self, caminho):
        if not os.path.isfile(caminho):
            self._json({"erro": "nao encontrado"}, 404)
            return
        ext = os.path.splitext(caminho)[1].lower()
        with open(caminho, "rb") as f:
            bruto = f.read()
        self.send_response(200)
        self.send_header("Content-Type", TIPOS.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(bruto)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(bruto)

    # ------------------------------------------------------------- GET

    def do_GET(self):
        rota = self.path.split("?", 1)[0]
        if rota == "/api/eventos":
            self._eventos()
            return
        if rota == "/api/insp":
            self._json({"insp": ESTADO.insp})
            return
        if rota in ("/", "/index.html"):
            self._arquivo(os.path.join(PASTA_WEB, "index.html"))
            return
        alvo = os.path.normpath(os.path.join(PASTA_WEB, rota.lstrip("/")))
        if not alvo.startswith(PASTA_WEB):
            self._json({"erro": "fora do diretorio"}, 403)
            return
        self._arquivo(alvo)

    def _eventos(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        fila = ESTADO.inscrever()
        try:
            while True:
                try:
                    item = fila.get(timeout=15)
                    bloco = "data: %s\n\n" % json.dumps(item, ensure_ascii=False)
                except queue.Empty:
                    bloco = ": ping\n\n"
                self.wfile.write(bloco.encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
            pass
        finally:
            ESTADO.desinscrever(fila)

    # ------------------------------------------------------------ POST

    def do_POST(self):
        rota = self.path.split("?", 1)[0]
        funcao = ROTAS.get(rota)
        if funcao is None:
            self._json({"erro": "rota desconhecida"}, 404)
            return
        try:
            tamanho = int(self.headers.get("Content-Length") or 0)
            corpo = json.loads(self.rfile.read(tamanho) or b"{}") if tamanho else {}
        except Exception as e:
            self._json({"erro": "corpo invalido: %s" % e}, 400)
            return
        try:
            self._json(funcao(corpo))
        except Exception as e:
            self._json({"erro": str(e)}, 500)


# ------------------------------------------------------------------ main

def porta_livre():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def vigia(servidor):
    """Desliga o servidor quando a pagina vai embora de verdade.

    Um lote em andamento segura o servidor: fechar a aba no meio de um
    render nao interrompe o lote.
    """
    while True:
        time.sleep(2)
        if ESTADO.processo is not None:
            ESTADO.ultimo_sinal = time.time()
            continue
        agendado = ESTADO.saindo_em
        if agendado is not None and time.time() >= agendado:
            break
        if time.time() - ESTADO.ultimo_sinal > SEGUNDOS_SEM_SINAL:
            break
    ESTADO.desligando = True
    servidor.shutdown()


def main():
    porta = porta_livre()
    endereco = "http://127.0.0.1:%d/" % porta
    servidor = ThreadingHTTPServer(("127.0.0.1", porta), Manipulador)
    servidor.daemon_threads = True

    print("Render de lote")
    print(endereco)
    print("(feche a aba do navegador para encerrar)")
    threading.Thread(target=vigia, args=(servidor,), daemon=True).start()
    threading.Thread(target=monitorar, daemon=True).start()
    try:
        webbrowser.open(endereco)
    except Exception:
        pass
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    if ESTADO.processo is not None:
        ESTADO.processo.terminate()
    print("encerrado")


if __name__ == "__main__":
    main()
