"""Logica compartilhada da automacao. Python puro, sem bpy.

Roda no Python do sistema. Conversa com o Blender por subprocesso.
"""

import json
import os
import re
import subprocess

AQUI = os.path.dirname(os.path.abspath(__file__))
MARCA_INI = "<<<INSPECAO>>>"
MARCA_FIM = "<<<FIM>>>"

BLENDERS_PROVAVEIS = [
    r"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 4.4\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 4.3\blender.exe",
]


def achar_blender(preferido=None):
    if preferido and os.path.exists(preferido):
        return preferido
    for c in BLENDERS_PROVAVEIS:
        if os.path.exists(c):
            return c
    base = r"C:\Program Files\Blender Foundation"
    if os.path.isdir(base):
        for nome in sorted(os.listdir(base), reverse=True):
            exe = os.path.join(base, nome, "blender.exe")
            if os.path.exists(exe):
                return exe
    return None


def sem_janela():
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return si
    return None


def inspecionar(blend, blender=None):
    """Abre o .blend em headless e devolve a estrutura da cena."""
    exe = achar_blender(blender)
    if not exe:
        raise RuntimeError(
            "Blender nao encontrado. Aponte o executavel na aba Projeto.")
    if not os.path.exists(blend):
        raise RuntimeError("arquivo nao encontrado: %s" % blend)

    cmd = [exe, "-b", blend, "--factory-startup", "-noaudio",
           "-P", os.path.join(AQUI, "inspecionar.py")]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", startupinfo=sem_janela())
    saida = r.stdout or ""
    if MARCA_INI not in saida:
        detalhe = (r.stderr or saida)[-2000:]
        raise RuntimeError("a inspecao falhou:\n%s" % detalhe)
    bruto = saida.split(MARCA_INI, 1)[1].split(MARCA_FIM, 1)[0]
    return json.loads(bruto)


# ------------------------------------------------------------------ config

def config_novo(blend=""):
    return {
        "blend": blend,
        "blender": "",
        "raiz": "",
        "template": "{aparelho}/{capinha}/{camera}/{numero}.png",
        "tokens": {"aparelho": "", "linha": ""},
        "qualidade": {"samples": 256, "resolucao": 1000, "gpu": True},
        "preview": {"samples": 32, "resolucao": 500, "gpu": True},
        "grupos": {
            "capinha": {"pecas": [], "variacoes": []},
            "corpo": {"pecas": [], "variacoes": []},
        },
        "cameras": [],
        "mascara": {"ativa": True, "objetos": [], "numero": "01", "samples": 8},
        "numero_inicial": 2,
    }


def salvar_config(cfg, caminho):
    pasta = os.path.dirname(caminho)
    if pasta:
        os.makedirs(pasta, exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=1)


def carregar_config(caminho):
    with open(caminho, encoding="utf-8") as f:
        cfg = json.load(f)
    base = config_novo()
    for k, v in base.items():
        cfg.setdefault(k, v)
    cfg.setdefault("grupos", {})
    for g in ("capinha", "corpo"):
        cfg["grupos"].setdefault(g, {"pecas": [], "variacoes": []})
        cfg["grupos"][g].setdefault("pecas", [])
        cfg["grupos"][g].setdefault("variacoes", [])
    return cfg


def sincronizar_cameras(cfg, insp):
    """Alinha a lista de cameras com o .blend, preservando rotulos ja dados."""
    antigas = {c["objeto"]: c for c in cfg.get("cameras", [])}
    novas = []
    for i, cam in enumerate(insp.get("cameras", []), 1):
        ant = antigas.get(cam["nome"], {})
        novas.append({
            "objeto": cam["nome"],
            "rotulo": ant.get("rotulo") or "POS %d" % i,
            "ativa": ant.get("ativa", True),
        })
    cfg["cameras"] = novas
    return novas


# --------------------------------------------------------------- resolucao

def entra_no_render(obj, insp):
    """Objeto que de fato aparece no render.

    Exclui o proprio objeto oculto e tambem os que estao em colecao
    oculta - e ali que costumam morar os cubos de swatch que apenas
    seguram os materiais para nao serem descartados. Se eles entrassem
    no mapeamento, cada troca reescreveria a biblioteca de materiais.
    """
    if obj.get("oculto"):
        return False
    ocultas = {c["nome"] for c in insp.get("colecoes", []) if c.get("oculta")}
    return not (set(obj.get("colecoes") or []) & ocultas)


def mapear_pecas(grupo, insp):
    """Descobre quais (objeto, slot) pertencem a cada peca (coluna).

    Um slot pertence a peca N se o material que esta nele agora aparece em
    alguma celula da coluna N. Sem indice de slot no config e sem depender
    de padrao de nome de material.
    """
    por_coluna = {}
    for var in grupo.get("variacoes", []):
        for idx, mat in enumerate(var.get("materiais", [])):
            if mat:
                por_coluna.setdefault(idx, set()).add(mat)

    mapa = {}
    for obj in insp.get("objetos", []):
        if not entra_no_render(obj, insp):
            continue
        for s in obj.get("slots", []):
            mat = s.get("material")
            if not mat:
                continue
            for idx, mats in por_coluna.items():
                if mat in mats:
                    mapa.setdefault(idx, []).append(
                        {"objeto": obj["nome"], "slot": s["slot"]})
    return mapa


def nome_peca(grupo, idx):
    pecas = grupo.get("pecas", [])
    if idx < len(pecas) and pecas[idx]:
        return pecas[idx]
    return "peca %d" % (idx + 1)


def conferir(cfg, insp):
    """Valida o config contra o .blend. Devolve (erros, avisos)."""
    erros, avisos = [], []
    existentes = {m["nome"] for m in insp.get("materiais", [])}

    for nome_grupo in ("capinha", "corpo"):
        g = cfg["grupos"][nome_grupo]
        variacoes = g.get("variacoes", [])
        if not variacoes:
            avisos.append("o grupo '%s' nao tem nenhuma variacao" % nome_grupo)
            continue

        dono = {}
        for var in variacoes:
            for idx, mat in enumerate(var.get("materiais", [])):
                if not mat:
                    continue
                if mat not in existentes:
                    erros.append("%s / %s: o material '%s' nao existe no .blend"
                                 % (nome_grupo, var.get("nome", "?"), mat))
                if mat in dono and dono[mat] != idx:
                    erros.append(
                        "'%s' aparece em duas pecas de %s ('%s' e '%s') - "
                        "fica ambiguo de qual peca ele e"
                        % (mat, nome_grupo, nome_peca(g, dono[mat]),
                           nome_peca(g, idx)))
                dono.setdefault(mat, idx)

        mapa = mapear_pecas(g, insp)
        for idx in range(len(g.get("pecas", []))):
            if idx not in mapa:
                avisos.append(
                    "a peca '%s' de %s nao casa com nenhum slot do arquivo"
                    % (nome_peca(g, idx), nome_grupo))

    if not cfg.get("raiz"):
        erros.append("a pasta raiz de saida nao foi definida")
    if not os.path.exists(cfg.get("blend") or ""):
        erros.append("o .blend nao foi encontrado")
    if not [c for c in cfg.get("cameras", []) if c.get("ativa")]:
        erros.append("nenhuma camera esta selecionada")

    return erros, avisos


PROIBIDOS = re.compile(r'[<>:"|?*]')


def limpar_pedaco(txt):
    return PROIBIDOS.sub("", str(txt or "")).strip().strip(".")


def montar_caminho(cfg, capinha, camera, numero):
    tokens = dict(cfg.get("tokens") or {})
    tokens.update({"capinha": capinha, "camera": camera, "numero": numero})
    rel = cfg.get("template") or "{capinha}/{camera}/{numero}.png"
    try:
        rel = rel.format(**tokens)
    except KeyError as e:
        raise RuntimeError("o template usa um marcador desconhecido: %s" % e)
    partes = [limpar_pedaco(p) for p in re.split(r"[\\/]+", rel)]
    partes = [p for p in partes if p]
    if not partes:
        raise RuntimeError("o template resultou em caminho vazio")
    return os.path.normpath(os.path.join(cfg["raiz"], *partes))


def atribuicoes_de(variacao, mapa):
    saida = []
    for idx, mat in enumerate(variacao.get("materiais", [])):
        if not mat:
            continue
        for alvo in mapa.get(idx, []):
            saida.append({"objeto": alvo["objeto"], "slot": alvo["slot"],
                          "material": mat})
    return saida


def montar_fila(cfg, insp, sel_capinha=None, sel_corpo=None, preview=False,
                forcar=False):
    """Monta o plano: jobs para o Blender + copias de mascara.

    A mascara e geometria pura, identica em todas as cores de capinha.
    Entao ela e renderizada uma vez por camera e copiada para as outras
    pastas depois do lote.
    """
    cap_grupo = cfg["grupos"]["capinha"]
    cor_grupo = cfg["grupos"]["corpo"]
    mapa_cap = mapear_pecas(cap_grupo, insp)
    mapa_cor = mapear_pecas(cor_grupo, insp)

    capinhas = cap_grupo.get("variacoes", [])
    corpos = cor_grupo.get("variacoes", [])
    if sel_capinha is not None:
        capinhas = [v for v in capinhas if v.get("nome") in sel_capinha]
    if sel_corpo is not None:
        corpos = [v for v in corpos if v.get("nome") in sel_corpo]

    cameras = [c for c in cfg.get("cameras", []) if c.get("ativa")]
    masc = cfg.get("mascara") or {}
    usa_mascara = bool(masc.get("ativa") and masc.get("objetos"))

    jobs, copias = [], []
    mascara_por_camera = {}

    for cap in capinhas:
        nome_cap = cap.get("nome") or "sem-nome"
        atribs_cap = atribuicoes_de(cap, mapa_cap)

        for cam in cameras:
            if usa_mascara:
                destino = montar_caminho(cfg, nome_cap, cam["rotulo"],
                                         masc.get("numero") or "01")
                origem = mascara_por_camera.get(cam["objeto"])
                if origem is None:
                    mascara_por_camera[cam["objeto"]] = destino
                    jobs.append({
                        "rotulo": "%s / %s / mascara" % (nome_cap, cam["rotulo"]),
                        "saida": destino.replace("\\", "/"),
                        "camera": cam["objeto"],
                        "visiveis": list(masc["objetos"]),
                        "samples": masc.get("samples") or 8,
                        "atribuicoes": [],
                    })
                elif os.path.normpath(origem) != os.path.normpath(destino):
                    copias.append([origem, destino])

            for cor in corpos:
                destino = montar_caminho(cfg, nome_cap, cam["rotulo"],
                                         cor.get("numero") or "02")
                jobs.append({
                    "rotulo": "%s / %s / %s %s" % (
                        nome_cap, cam["rotulo"], cor.get("numero", ""),
                        cor.get("nome", "")),
                    "saida": destino.replace("\\", "/"),
                    "camera": cam["objeto"],
                    "visiveis": None,
                    "samples": None,
                    "atribuicoes": atribs_cap + atribuicoes_de(cor, mapa_cor),
                })

    qual = dict((cfg.get("preview") if preview else cfg.get("qualidade")) or {})
    return {"forcar": bool(forcar), "qualidade": qual, "jobs": jobs,
            "copias": copias}


def renumerar(grupo, inicial=2):
    """Preenche a coluna de numero pela ordem das linhas."""
    for i, var in enumerate(grupo.get("variacoes", [])):
        var["numero"] = "%02d" % (int(inicial) + i)


def comando_render(cfg, caminho_fila):
    exe = achar_blender(cfg.get("blender"))
    if not exe:
        raise RuntimeError("Blender nao encontrado.")
    return [exe, "-b", cfg["blend"], "--factory-startup", "-noaudio",
            "-P", os.path.join(AQUI, "render.py"), "--", caminho_fila]
