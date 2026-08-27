"""Roda DENTRO do Blender. Executa uma fila de renders.

Uso:
    blender -b arquivo.blend -P render.py -- fila.json

Nunca salva o .blend. Todas as alteracoes ficam em memoria e sao
descartadas ao sair.

A fila e um JSON:
{
  "forcar": false,
  "qualidade": {"samples": 256, "resolucao": 1000, "gpu": true},
  "jobs": [
    {
      "rotulo": "Slim Guard Azul / POS 1 / 02",
      "saida": "C:/.../POS 1/02.png",
      "camera": "Camera",
      "atribuicoes": [{"objeto": "capa", "slot": 0, "material": "case azul"}],
      "visiveis": null,
      "samples": null
    }
  ]
}

"visiveis" com uma lista de nomes = renderiza SO esses objetos de malha
(usado para a mascara). null = respeita a visibilidade do arquivo.
"""

import bpy
import json
import os
import sys
import time


def log(*partes):
    print("LOTE|", *partes, flush=True)


def argumentos():
    argv = sys.argv
    if "--" in argv:
        return argv[argv.index("--") + 1:]
    return []


def carregar_fila():
    extra = argumentos()
    if not extra:
        raise SystemExit("LOTE| ERRO falta o caminho do arquivo de fila")
    with open(extra[0], encoding="utf-8") as f:
        return json.load(f)


def ativar_gpu(sc):
    """Em background mode o Cycles nao usa GPU sozinho."""
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
    except Exception as e:
        log("GPU indisponivel:", e)
        sc.cycles.device = "CPU"
        return

    for tipo in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"):
        try:
            prefs.compute_device_type = tipo
        except Exception:
            continue
        try:
            prefs.refresh_devices()
        except Exception:
            pass
        disponiveis = [d for d in prefs.devices if d.type == tipo]
        if not disponiveis:
            continue
        for d in prefs.devices:
            d.use = (d.type == tipo)
        sc.cycles.device = "GPU"
        log("GPU", tipo, "->", ", ".join(d.name for d in disponiveis))
        return

    log("GPU nenhuma encontrada, usando CPU")
    sc.cycles.device = "CPU"


def aplicar_qualidade(sc, q):
    if q.get("samples"):
        try:
            sc.cycles.samples = int(q["samples"])
        except Exception:
            pass
    if q.get("resolucao"):
        lado = int(q["resolucao"])
        sc.render.resolution_x = lado
        sc.render.resolution_y = lado
        sc.render.resolution_percentage = 100
    if q.get("gpu", True):
        ativar_gpu(sc)


def malhas():
    return [o for o in bpy.data.objects if o.type == "MESH"]


def aplicar_visibilidade(visiveis, original):
    """visiveis=None restaura o arquivo. Lista = so esses aparecem."""
    if visiveis is None:
        for o in malhas():
            o.hide_render = original.get(o.name, o.hide_render)
        return
    alvo = set(visiveis)
    for o in malhas():
        o.hide_render = o.name not in alvo


def aplicar_atribuicoes(atribuicoes):
    problemas = []
    for a in atribuicoes or []:
        obj = bpy.data.objects.get(a["objeto"])
        if obj is None:
            problemas.append("objeto ausente: %s" % a["objeto"])
            continue
        mat = bpy.data.materials.get(a["material"])
        if mat is None:
            problemas.append("material ausente: %s" % a["material"])
            continue
        idx = int(a["slot"])
        if idx >= len(obj.material_slots):
            problemas.append("slot %d fora de alcance em %s" % (idx, obj.name))
            continue
        obj.material_slots[idx].material = mat
    return problemas


def main():
    fila = carregar_fila()
    sc = bpy.context.scene

    original = {o.name: o.hide_render for o in malhas()}
    samples_base = None
    try:
        samples_base = sc.cycles.samples
    except Exception:
        pass

    aplicar_qualidade(sc, fila.get("qualidade") or {})
    if samples_base is None:
        samples_base = 128
    else:
        samples_base = sc.cycles.samples

    jobs = fila.get("jobs") or []
    total = len(jobs)
    forcar = bool(fila.get("forcar"))

    log("TOTAL", total)
    feitos = pulados = falhos = 0
    inicio_lote = time.time()

    for i, job in enumerate(jobs, 1):
        rotulo = job.get("rotulo") or job.get("saida", "?")
        saida = job["saida"]

        if os.path.exists(saida) and not forcar:
            pulados += 1
            log("PULADO", i, total, rotulo)
            continue

        cam = bpy.data.objects.get(job["camera"])
        if cam is None or cam.type != "CAMERA":
            falhos += 1
            log("FALHA", i, total, rotulo, "camera ausente: %s" % job["camera"])
            continue
        sc.camera = cam

        problemas = aplicar_atribuicoes(job.get("atribuicoes"))
        if problemas:
            falhos += 1
            log("FALHA", i, total, rotulo, "; ".join(problemas))
            continue

        aplicar_visibilidade(job.get("visiveis"), original)

        try:
            sc.cycles.samples = int(job.get("samples") or samples_base)
        except Exception:
            pass

        pasta = os.path.dirname(saida)
        if pasta:
            os.makedirs(pasta, exist_ok=True)
        sc.render.filepath = saida

        log("INICIO", i, total, rotulo)
        t0 = time.time()
        try:
            bpy.ops.render.render(write_still=True)
        except Exception as e:
            falhos += 1
            log("FALHA", i, total, rotulo, str(e))
            continue
        gasto = round(time.time() - t0, 1)

        if os.path.exists(saida):
            feitos += 1
            log("OK", i, total, rotulo, "%ss" % gasto, saida)
        else:
            falhos += 1
            log("FALHA", i, total, rotulo, "arquivo nao apareceu em %s" % saida)

    aplicar_visibilidade(None, original)
    log("FIM", "feitos=%d" % feitos, "pulados=%d" % pulados,
        "falhos=%d" % falhos, "tempo=%ss" % round(time.time() - inicio_lote, 1))


main()
