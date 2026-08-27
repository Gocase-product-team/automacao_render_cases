"""Roda DENTRO do Blender. Despeja a estrutura da cena em JSON.

Uso:
    blender -b arquivo.blend -P inspecionar.py -- saida.json
"""

import bpy
import json
import sys

MARCA_INI = "<<<INSPECAO>>>"
MARCA_FIM = "<<<FIM>>>"


def argumentos():
    argv = sys.argv
    if "--" in argv:
        return argv[argv.index("--") + 1:]
    return []


def _byte(c):
    """Linear para sRGB, em 0..255."""
    c = max(0.0, min(1.0, float(c)))
    if c <= 0.0031308:
        v = c * 12.92
    else:
        v = 1.055 * (c ** (1.0 / 2.4)) - 0.055
    return int(round(max(0.0, min(1.0, v)) * 255))


def _hex(rgb):
    return "#%02x%02x%02x" % (_byte(rgb[0]), _byte(rgb[1]), _byte(rgb[2]))


def cor_do_material(m):
    """Cor representativa para o quadradinho da interface.

    Nos plasticos translucidos a cor visivel nao esta no Base Color (que e
    branco) e sim no no de Volume Absorption. Por isso a absorcao tem
    prioridade quando a transmissao esta ligada. Devolve None quando o
    material e regido por textura, sem cor unica.
    """
    if not m.use_nodes or not m.node_tree:
        try:
            return _hex(m.diffuse_color[:3])
        except Exception:
            return None

    principled = absorcao = rgb = emissao = None
    tem_textura = False
    for n in m.node_tree.nodes:
        if n.type == "BSDF_PRINCIPLED" and principled is None:
            principled = n
        elif n.type == "VOLUME_ABSORPTION" and absorcao is None:
            absorcao = n
        elif n.type == "RGB" and rgb is None:
            rgb = n
        elif n.type == "EMISSION" and emissao is None:
            emissao = n
        elif n.type == "TEX_IMAGE":
            tem_textura = True

    if absorcao is not None and principled is not None:
        try:
            t = principled.inputs["Transmission Weight"]
            if not t.is_linked and t.default_value > 0.5:
                return _hex(absorcao.inputs["Color"].default_value[:3])
        except Exception:
            pass

    if principled is not None:
        try:
            bc = principled.inputs["Base Color"]
            if not bc.is_linked:
                return _hex(bc.default_value[:3])
        except Exception:
            pass

    if absorcao is not None:
        try:
            return _hex(absorcao.inputs["Color"].default_value[:3])
        except Exception:
            pass

    for no in (rgb, emissao):
        if no is None:
            continue
        try:
            saida = no.outputs[0] if no is rgb else None
            if saida is not None and not saida.is_linked:
                return _hex(saida.default_value[:3])
            if no is rgb:
                return _hex(no.outputs[0].default_value[:3])
            return _hex(no.inputs["Color"].default_value[:3])
        except Exception:
            continue

    if tem_textura:
        return None
    return None


def dispositivos():
    """Hardware de render disponivel, na mesma ordem de preferencia que o
    render.py usa.

    Isto NAO vem do .blend - a cena guarda apenas 'GPU' ou 'CPU'. Qual
    placa e qual backend vem das preferencias do Blender e do hardware.
    Como rodamos com --factory-startup, a escolha salva do usuario esta
    zerada, mas a enumeracao do hardware continua funcionando: e assim
    que o render.py descobre a placa.
    """
    saida = {"backend": None, "nome": None, "cpu": None, "lista": []}
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
    except Exception:
        return saida

    for tipo in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"):
        try:
            prefs.compute_device_type = tipo
        except Exception:
            continue
        try:
            prefs.refresh_devices()
        except Exception:
            pass
        achados = [d.name for d in prefs.devices if d.type == tipo]
        for nome in achados:
            saida["lista"].append({"tipo": tipo, "nome": nome})
        if achados and saida["backend"] is None:
            saida["backend"] = tipo
            saida["nome"] = achados[0]

    for d in prefs.devices:
        if d.type == "CPU":
            saida["cpu"] = d.name
            break

    return saida


def coletar():
    sc = bpy.context.scene

    dados = {
        "blend": bpy.data.filepath,
        "cena": sc.name,
        "engine": sc.render.engine,
        "resolucao": [sc.render.resolution_x, sc.render.resolution_y],
        "porcentagem": sc.render.resolution_percentage,
        "formato": sc.render.image_settings.file_format,
        "modo_cor": sc.render.image_settings.color_mode,
        "fundo_transparente": sc.render.film_transparent,
        "camera_ativa": sc.camera.name if sc.camera else None,
        "cameras": [],
        "materiais": [],
        "objetos": [],
        "colecoes": [],
    }

    try:
        dados["cycles"] = {
            "device": sc.cycles.device,
            "samples": sc.cycles.samples,
            "denoise": sc.cycles.use_denoising,
        }
    except Exception:
        dados["cycles"] = None

    dados["dispositivos"] = dispositivos()

    for o in sorted((o for o in bpy.data.objects if o.type == "CAMERA"), key=lambda x: x.name):
        dados["cameras"].append({
            "nome": o.name,
            "lente": round(o.data.lens, 2),
            "posicao": [round(v, 3) for v in o.location],
            "rotacao": [round(v, 4) for v in o.rotation_euler],
            "oculta": o.hide_render,
        })

    usos = {}
    for o in sorted(bpy.data.objects, key=lambda x: x.name):
        if o.type != "MESH":
            continue
        por_slot = {}
        for f in o.data.polygons:
            por_slot[f.material_index] = por_slot.get(f.material_index, 0) + 1
        slots = []
        for i, s in enumerate(o.material_slots):
            nome = s.material.name if s.material else None
            faces = por_slot.get(i, 0)
            slots.append({"slot": i, "material": nome, "faces": faces})
            if nome:
                usos.setdefault(nome, []).append({
                    "objeto": o.name, "slot": i, "faces": faces,
                })
        dados["objetos"].append({
            "nome": o.name,
            "oculto": o.hide_render,
            "faces": len(o.data.polygons),
            "colecoes": [c.name for c in o.users_collection],
            "slots": slots,
        })

    for m in sorted(bpy.data.materials, key=lambda x: x.name.lower()):
        lista = usos.get(m.name, [])
        dados["materiais"].append({
            "nome": m.name,
            "usos": lista,
            "faces": sum(u["faces"] for u in lista),
            "slots_ocupados": len(lista),
            "cor": cor_do_material(m),
        })

    for c in sorted(bpy.data.collections, key=lambda x: x.name):
        dados["colecoes"].append({
            "nome": c.name,
            "oculta": c.hide_render,
            "objetos": len(c.objects),
        })

    return dados


def main():
    dados = coletar()
    texto = json.dumps(dados, ensure_ascii=False, indent=1)

    extra = argumentos()
    if extra:
        with open(extra[0], "w", encoding="utf-8") as f:
            f.write(texto)

    print(MARCA_INI)
    print(texto)
    print(MARCA_FIM)


main()
