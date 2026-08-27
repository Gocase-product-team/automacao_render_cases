"""Interface do render de lote. Roda no Python do sistema, nao no Blender.

    python app.py
"""

import json
import os
import queue
import shutil
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import nucleo

AQUI = os.path.dirname(os.path.abspath(__file__))
PASTA_PROJETOS = os.path.join(AQUI, "projetos")
VAZIO = "—"
COR_ICO = "#3a3f46"


# ------------------------------------------------------------------ icones
# Desenhados em codigo com PhotoImage. Evita depender de fonte de emoji,
# que no Tk do Windows costuma sair como quadradinho vazio.

def _tela(n=16):
    return tk.PhotoImage(width=n, height=n)


def ico_mais():
    im = _tela()
    im.put(COR_ICO, to=(7, 3, 9, 13))
    im.put(COR_ICO, to=(3, 7, 13, 9))
    return im


def ico_lixeira():
    im = _tela()
    im.put(COR_ICO, to=(6, 2, 10, 3))
    im.put(COR_ICO, to=(3, 4, 13, 6))
    im.put(COR_ICO, to=(4, 6, 6, 14))
    im.put(COR_ICO, to=(10, 6, 12, 14))
    im.put(COR_ICO, to=(4, 12, 12, 14))
    im.put(COR_ICO, to=(7, 7, 9, 12))
    return im


def ico_lapis():
    im = _tela()
    for i in range(9):
        im.put(COR_ICO, to=(4 + i, 11 - i, 7 + i, 14 - i))
    im.put(COR_ICO, to=(2, 12, 5, 15))
    return im


def ico_seta(cima=True):
    im = _tela()
    for i in range(6):
        larg = 1 + i * 2
        x = 8 - larg // 2
        y = (4 + i) if cima else (11 - i)
        im.put(COR_ICO, to=(x, y, x + larg, y + 1))
    return im


def ico_lista():
    im = _tela()
    for y in (4, 8, 12):
        im.put(COR_ICO, to=(2, y, 5, y + 2))
        im.put(COR_ICO, to=(7, y, 14, y + 2))
    return im


def ico_play():
    im = _tela()
    for i in range(6):
        topo, base = 3 + i, 13 - i
        if topo >= base:
            break
        im.put(COR_ICO, to=(5 + i, topo, 6 + i, base))
    return im


def ico_parar():
    im = _tela()
    im.put(COR_ICO, to=(4, 4, 12, 12))
    return im


def ico_check():
    im = _tela()
    for i in range(4):
        im.put(COR_ICO, to=(3 + i, 8 + i, 5 + i, 10 + i))
    for i in range(7):
        im.put(COR_ICO, to=(6 + i, 11 - i, 8 + i, 13 - i))
    return im


def ico_olho():
    im = _tela()
    im.put(COR_ICO, to=(3, 7, 13, 9))
    im.put(COR_ICO, to=(5, 5, 11, 7))
    im.put(COR_ICO, to=(5, 9, 11, 11))
    im.put("#ffffff", to=(7, 7, 9, 9))
    return im


def ico_pasta():
    im = _tela()
    im.put(COR_ICO, to=(2, 3, 7, 5))
    im.put(COR_ICO, to=(2, 5, 14, 13))
    return im


def ico_disco():
    im = _tela()
    im.put(COR_ICO, to=(3, 3, 13, 13))
    im.put("#ffffff", to=(6, 4, 10, 7))
    return im


def ico_folha():
    im = _tela()
    im.put(COR_ICO, to=(4, 2, 12, 14))
    im.put("#ffffff", to=(6, 5, 10, 6))
    im.put("#ffffff", to=(6, 8, 10, 9))
    return im


def ico_lupa():
    im = _tela()
    im.put(COR_ICO, to=(3, 3, 11, 5))
    im.put(COR_ICO, to=(3, 9, 11, 11))
    im.put(COR_ICO, to=(3, 3, 5, 11))
    im.put(COR_ICO, to=(9, 3, 11, 11))
    for i in range(4):
        im.put(COR_ICO, to=(10 + i, 10 + i, 12 + i, 12 + i))
    return im


def amostra(cor, n=13):
    """Quadradinho de cor. Xadrez quando o material e regido por textura."""
    im = tk.PhotoImage(width=n, height=n)
    im.put("#9aa0a6", to=(0, 0, n, n))
    if cor:
        im.put(cor, to=(1, 1, n - 1, n - 1))
    else:
        meio = n // 2
        im.put("#eaeaea", to=(1, 1, n - 1, n - 1))
        im.put("#b6b6b6", to=(1, 1, meio, meio))
        im.put("#b6b6b6", to=(meio, meio, n - 1, n - 1))
    return im


# ------------------------------------------------------------------ apoio

class QuadroRolavel(ttk.Frame):
    """Area com barra de rolagem que aceita widgets de verdade dentro."""

    def __init__(self, pai, altura=170):
        super().__init__(pai)
        self.canvas = tk.Canvas(self, highlightthickness=0, height=altura,
                                background="#ffffff")
        barra = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.interno = ttk.Frame(self.canvas, padding=(4, 2))
        self.canvas.configure(yscrollcommand=barra.set)
        barra.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.janela = self.canvas.create_window((0, 0), window=self.interno,
                                                anchor="nw")
        self.interno.bind("<Configure>", self._recalcular)
        self.canvas.bind("<Configure>", self._esticar)
        for alvo in (self.canvas, self.interno):
            alvo.bind("<MouseWheel>", self._roda)

    def _recalcular(self, _=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _esticar(self, evento):
        self.canvas.itemconfig(self.janela, width=evento.width)

    def _roda(self, evento):
        self.canvas.yview_scroll(int(-evento.delta / 120), "units")

    def limpar(self):
        for w in self.interno.winfo_children():
            w.destroy()


class Arrastador:
    """Arrasta uma linha da lista de materiais para uma celula de grade."""

    def __init__(self, app, origem, pegar):
        self.app = app
        self.origem = origem
        self.pegar = pegar
        self.carga = None
        self.fantasma = None
        origem.bind("<ButtonPress-1>", self.pressionar, add="+")
        origem.bind("<B1-Motion>", self.mover, add="+")
        origem.bind("<ButtonRelease-1>", self.soltar, add="+")

    def pressionar(self, evento):
        self.carga = self.pegar(evento)

    def mover(self, evento):
        if not self.carga:
            return
        if self.fantasma is None:
            self.fantasma = tk.Toplevel(self.app)
            self.fantasma.overrideredirect(True)
            try:
                self.fantasma.attributes("-topmost", True)
            except tk.TclError:
                pass
            tk.Label(self.fantasma, text=self.carga, bg="#fff8c4",
                     relief="solid", bd=1, padx=6, pady=2).pack()
        self.fantasma.geometry("+%d+%d" % (evento.x_root + 14,
                                           evento.y_root + 10))

    def soltar(self, evento):
        if self.fantasma is not None:
            self.fantasma.destroy()
            self.fantasma = None
        carga, self.carga = self.carga, None
        if carga:
            self.app.receber(evento.x_root, evento.y_root, carga)


# -------------------------------------------------------------------- app

class App(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("Render de lote")
        self.geometry("1200x790")
        self.minsize(1020, 660)

        self.cfg = nucleo.config_novo()
        self.insp = None
        self.caminho_cfg = None
        self.processo = None
        self.linhas = queue.Queue()
        self.grades = {}
        self.materiais = []
        self.objetos = []
        self.amostras = {}
        self.cam_linhas = []
        self.masc_vars = {}
        self.sel_vars = {"capinha": [], "corpo": []}
        self.copias_pendentes = []
        # enquanto ligado, _colher nao escreve no cfg. Sem isso os traces
        # disparam durante o carregamento e apagam valores que ainda nao
        # chegaram nos widgets.
        self.carregando = False

        self.ico = {
            "mais": ico_mais(), "mais2": ico_mais(),
            "lapis": ico_lapis(), "lixo": ico_lixeira(), "lixo2": ico_lixeira(),
            "cima": ico_seta(True), "baixo": ico_seta(False),
            "lista": ico_lista(), "play": ico_play(), "parar": ico_parar(),
            "check": ico_check(), "olho": ico_olho(), "pasta": ico_pasta(),
            "disco": ico_disco(), "folha": ico_folha(), "lupa": ico_lupa(),
        }

        estilo = ttk.Style(self)
        estilo.configure("Treeview", rowheight=21)

        self._montar()
        self.after(120, self._drenar)
        self.protocol("WM_DELETE_WINDOW", self._fechar)

    def _bt(self, pai, texto, icone, comando, **kw):
        b = ttk.Button(pai, text=" " + texto, image=self.ico[icone],
                       compound="left", command=comando, **kw)
        return b

    # ------------------------------------------------------------ layout

    def _montar(self):
        topo = ttk.Frame(self, padding=(10, 8))
        topo.pack(fill="x")
        self._bt(topo, "Novo", "folha", self.projeto_novo).pack(side="left")
        self._bt(topo, "Abrir", "pasta", self.projeto_abrir).pack(side="left", padx=4)
        self._bt(topo, "Salvar", "disco", self.projeto_salvar).pack(side="left")
        self.rotulo_projeto = ttk.Label(topo, text="projeto novo", foreground="#666")
        self.rotulo_projeto.pack(side="left", padx=12)

        self.abas = ttk.Notebook(self)
        self.abas.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        self._aba_projeto()
        self._aba_pecas()
        self._aba_cameras()
        self._aba_render()

        self.barra = ttk.Label(self, text="pronto", anchor="w",
                               relief="sunken", padding=(8, 3))
        self.barra.pack(fill="x", side="bottom")

    def _campo(self, pai, rotulo, largura=64, valor=None, procurar=None):
        quadro = ttk.Frame(pai)
        quadro.pack(fill="x", pady=3)
        ttk.Label(quadro, text=rotulo, width=18).pack(side="left")
        var = tk.StringVar(value=valor or "")
        ttk.Entry(quadro, textvariable=var, width=largura).pack(
            side="left", fill="x", expand=True)
        if procurar:
            ttk.Button(quadro, text="...", width=3,
                       command=lambda: self._procurar(var, procurar)).pack(
                side="left", padx=4)
        return var

    def _procurar(self, var, modo):
        if modo == "blend":
            c = filedialog.askopenfilename(title="Escolha o .blend",
                                           filetypes=[("Blender", "*.blend")])
        elif modo == "exe":
            c = filedialog.askopenfilename(title="Escolha o blender.exe",
                                           filetypes=[("Executavel", "*.exe")])
        else:
            c = filedialog.askdirectory(title="Escolha a pasta")
        if c:
            var.set(os.path.normpath(c))

    # ----------------------------------------------------- aba projeto

    def _aba_projeto(self):
        aba = ttk.Frame(self.abas, padding=14)
        self.abas.add(aba, text="Projeto")

        cx = ttk.LabelFrame(aba, text="Arquivo", padding=10)
        cx.pack(fill="x")
        self.v_blend = self._campo(cx, "arquivo .blend", procurar="blend")
        self.v_exe = self._campo(cx, "blender.exe", procurar="exe",
                                 valor=nucleo.achar_blender() or "")
        linha = ttk.Frame(cx)
        linha.pack(fill="x", pady=(6, 0))
        ttk.Label(linha, text="", width=18).pack(side="left")
        self._bt(linha, "Inspecionar o .blend", "lupa", self.inspecionar).pack(side="left")
        self.rotulo_insp = ttk.Label(linha, text="nao inspecionado", foreground="#888")
        self.rotulo_insp.pack(side="left", padx=10)

        cx = ttk.LabelFrame(aba, text="Saida", padding=10)
        cx.pack(fill="x", pady=10)
        self.v_raiz = self._campo(cx, "pasta raiz", procurar="pasta")
        self.v_template = self._campo(
            cx, "template", valor="{aparelho}/{capinha}/{camera}/{numero}.png")
        self.v_aparelho = self._campo(cx, "aparelho")
        self.v_linha = self._campo(cx, "linha")
        ttk.Label(cx, foreground="#666", text=(
            "marcadores: {aparelho}  {linha}  {capinha}  {camera}  {numero}"
        )).pack(anchor="w", pady=(6, 0))
        self.previa_caminho = ttk.Label(cx, foreground="#0a7a3a",
                                        font=("Consolas", 9))
        self.previa_caminho.pack(anchor="w", pady=(4, 0))
        for v in (self.v_raiz, self.v_template, self.v_aparelho, self.v_linha):
            v.trace_add("write", lambda *a: self._atualizar_previa())

        cx = ttk.LabelFrame(aba, text="Qualidade", padding=10)
        cx.pack(fill="x")
        g = ttk.Frame(cx)
        g.pack(fill="x")
        ttk.Label(g, text="final", width=10).grid(row=0, column=0, sticky="w")
        ttk.Label(g, text="samples").grid(row=0, column=1, padx=(0, 4))
        self.v_samples = tk.StringVar(value="256")
        ttk.Entry(g, textvariable=self.v_samples, width=7).grid(row=0, column=2)
        ttk.Label(g, text="resolucao").grid(row=0, column=3, padx=(12, 4))
        self.v_res = tk.StringVar(value="1000")
        ttk.Entry(g, textvariable=self.v_res, width=7).grid(row=0, column=4)

        ttk.Label(g, text="preview", width=10).grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Label(g, text="samples").grid(row=1, column=1, pady=(6, 0))
        self.v_psamples = tk.StringVar(value="32")
        ttk.Entry(g, textvariable=self.v_psamples, width=7).grid(row=1, column=2, pady=(6, 0))
        ttk.Label(g, text="resolucao").grid(row=1, column=3, padx=(12, 4), pady=(6, 0))
        self.v_pres = tk.StringVar(value="500")
        ttk.Entry(g, textvariable=self.v_pres, width=7).grid(row=1, column=4, pady=(6, 0))

        self.v_gpu = tk.BooleanVar(value=True)
        ttk.Checkbutton(cx, text="forcar GPU no Cycles (necessario em background)",
                        variable=self.v_gpu).pack(anchor="w", pady=(8, 0))

    def _atualizar_previa(self):
        self._colher()
        try:
            cap = "capinha"
            if self.cfg["grupos"]["capinha"]["variacoes"]:
                cap = self.cfg["grupos"]["capinha"]["variacoes"][0].get("nome") or cap
            cam = self.cfg["cameras"][0]["rotulo"] if self.cfg["cameras"] else "POS 1"
            self.previa_caminho.config(
                text=nucleo.montar_caminho(self.cfg, cap, cam, "02"))
        except Exception as e:
            self.previa_caminho.config(text="(%s)" % e)

    # ------------------------------------------------------- aba pecas

    def _aba_pecas(self):
        aba = ttk.Frame(self.abas, padding=10)
        self.abas.add(aba, text="Pecas e variacoes")

        esq = ttk.LabelFrame(aba, text="Todos os materiais", padding=8)
        esq.pack(side="left", fill="y")
        ttk.Label(esq, foreground="#666", wraplength=250, text=(
            "arraste um material para uma celula da grade. "
            "o xadrez indica material regido por textura."
        )).pack(anchor="w", pady=(0, 6))
        quadro = ttk.Frame(esq)
        quadro.pack(fill="both", expand=True)
        barra = ttk.Scrollbar(quadro, orient="vertical")
        self.tv_mat = ttk.Treeview(quadro, show="tree", height=27,
                                   selectmode="browse",
                                   yscrollcommand=barra.set)
        self.tv_mat.column("#0", width=250, stretch=True)
        barra.config(command=self.tv_mat.yview)
        barra.pack(side="right", fill="y")
        self.tv_mat.pack(side="left", fill="both", expand=True)
        Arrastador(self, self.tv_mat, self._pegar_material)

        dir_ = ttk.Frame(aba)
        dir_.pack(side="left", fill="both", expand=True, padx=(10, 0))
        self._grade(dir_, "capinha", "Capinha  -  define o nome da pasta")
        self._grade(dir_, "corpo", "Corpo  -  define o numero do arquivo")
        ttk.Label(dir_, foreground="#666", text=(
            "duplo clique: editar nome/numero, ou limpar uma celula de material"
        )).pack(anchor="w", pady=(6, 0))

    def _grade(self, pai, nome, titulo):
        cx = ttk.LabelFrame(pai, text=titulo, padding=8)
        cx.pack(fill="both", expand=True, pady=(0, 8))

        barra = ttk.Frame(cx)
        barra.pack(fill="x", pady=(0, 6))
        self._bt(barra, "peca", "mais",
                 lambda: self.peca_nova(nome)).pack(side="left")
        self._bt(barra, "variacao", "mais2",
                 lambda: self.variacao_nova(nome)).pack(side="left", padx=3)
        self._bt(barra, "renomear peca", "lapis",
                 lambda: self.peca_renomear(nome)).pack(side="left", padx=(10, 3))
        self._bt(barra, "remover peca", "lixo",
                 lambda: self.peca_remover(nome)).pack(side="left")
        self._bt(barra, "remover variacao", "lixo2",
                 lambda: self.variacao_remover(nome)).pack(side="left", padx=3)
        self._bt(barra, "", "cima",
                 lambda: self.variacao_mover(nome, -1)).pack(side="left", padx=(10, 0))
        self._bt(barra, "", "baixo",
                 lambda: self.variacao_mover(nome, 1)).pack(side="left", padx=2)
        if nome == "corpo":
            self._bt(barra, "renumerar", "lista",
                     self.renumerar).pack(side="left", padx=(10, 0))

        tv = ttk.Treeview(cx, show="headings", height=6, selectmode="browse")
        tv.pack(fill="both", expand=True)
        tv.bind("<Double-1>", lambda e, n=nome: self._duplo(e, n))
        self.grades[nome] = tv

    # ----------------------------------------------------- aba cameras

    def _aba_cameras(self):
        aba = ttk.Frame(self.abas, padding=14)
        self.abas.add(aba, text="Cameras e mascara")

        cx = ttk.LabelFrame(aba, text="Cameras do arquivo", padding=10)
        cx.pack(fill="both", expand=True)
        ttk.Label(cx, foreground="#666", text=(
            "marque as que vao entrar no lote. o rotulo e o que vira pasta."
        )).pack(anchor="w", pady=(0, 6))
        cab = ttk.Frame(cx)
        cab.pack(fill="x")
        ttk.Label(cab, text="usar", width=6, foreground="#888").pack(side="left")
        ttk.Label(cab, text="nome no .blend", width=30, foreground="#888").pack(side="left")
        ttk.Label(cab, text="rotulo na saida", width=22, foreground="#888").pack(side="left")
        ttk.Label(cab, text="lente", foreground="#888").pack(side="left")
        self.rol_cam = QuadroRolavel(cx, altura=150)
        self.rol_cam.pack(fill="both", expand=True, pady=(4, 0))

        cx = ttk.LabelFrame(aba, text="Mascara", padding=10)
        cx.pack(fill="both", expand=True, pady=(10, 0))
        alto = ttk.Frame(cx)
        alto.pack(fill="x")
        self.v_masc = tk.BooleanVar(value=True)
        ttk.Checkbutton(alto, text="gerar mascara por camera", variable=self.v_masc,
                        command=self.recontar).pack(side="left")
        ttk.Label(alto, text="numero").pack(side="left", padx=(20, 4))
        self.v_masc_num = tk.StringVar(value="01")
        ttk.Entry(alto, textvariable=self.v_masc_num, width=6).pack(side="left")
        ttk.Label(alto, text="samples").pack(side="left", padx=(14, 4))
        self.v_masc_spp = tk.StringVar(value="8")
        ttk.Entry(alto, textvariable=self.v_masc_spp, width=6).pack(side="left")
        ttk.Label(cx, foreground="#666", wraplength=880, text=(
            "marque os objetos que aparecem na mascara. o resto e escondido "
            "durante esse render. e geometria pura, entao renderiza uma vez "
            "por camera e e copiada para as outras pastas de capinha."
        )).pack(anchor="w", pady=(8, 4))
        self.rol_masc = QuadroRolavel(cx, altura=150)
        self.rol_masc.pack(fill="both", expand=True)

    # ------------------------------------------------------ aba render

    def _aba_render(self):
        aba = ttk.Frame(self.abas, padding=12)
        self.abas.add(aba, text="Render")

        alto = ttk.Frame(aba)
        alto.pack(fill="x")
        self.rol_sel = {}
        for chave, titulo in (("capinha", "Capinhas"), ("corpo", "Corpos")):
            cx = ttk.LabelFrame(alto, text=titulo, padding=8)
            cx.pack(side="left", fill="both", expand=True, padx=(0, 8))
            rol = QuadroRolavel(cx, altura=140)
            rol.pack(fill="both", expand=True)
            self.rol_sel[chave] = rol

        cx = ttk.Frame(aba, padding=(0, 10))
        cx.pack(fill="x")
        self.v_modo = tk.StringVar(value="final")
        ttk.Radiobutton(cx, text="final", variable=self.v_modo,
                        value="final", command=self.recontar).pack(side="left")
        ttk.Radiobutton(cx, text="preview", variable=self.v_modo,
                        value="preview", command=self.recontar).pack(side="left", padx=(6, 14))
        self.v_forcar = tk.BooleanVar(value=False)
        ttk.Checkbutton(cx, text="refazer o que ja existe", variable=self.v_forcar,
                        command=self.recontar).pack(side="left")

        self.rotulo_conta = ttk.Label(cx, text="0 renders", font=("", 10, "bold"))
        self.rotulo_conta.pack(side="left", padx=16)

        self._bt(cx, "Conferir", "check", self.conferir).pack(side="right")
        self._bt(cx, "Dry-run", "olho", self.dry_run).pack(side="right", padx=5)
        self.botao_render = self._bt(cx, "Renderizar", "play", self.renderizar)
        self.botao_render.pack(side="right")
        self.botao_parar = self._bt(cx, "Parar", "parar", self.parar,
                                    state="disabled")
        self.botao_parar.pack(side="right", padx=5)

        self.progresso = ttk.Progressbar(aba, mode="determinate")
        self.progresso.pack(fill="x", pady=(0, 6))

        quadro = ttk.Frame(aba)
        quadro.pack(fill="both", expand=True)
        barra = ttk.Scrollbar(quadro, orient="vertical")
        self.log = tk.Text(quadro, height=13, font=("Consolas", 9), wrap="none",
                           yscrollcommand=barra.set)
        barra.config(command=self.log.yview)
        barra.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        self.log.tag_config("ok", foreground="#0a7a3a")
        self.log.tag_config("erro", foreground="#b02020")
        self.log.tag_config("info", foreground="#666666")

    # -------------------------------------------------------- utilidades

    def escrever(self, texto, tag=None):
        self.log.insert("end", texto + "\n", tag or ())
        self.log.see("end")

    def _pegar_material(self, evento):
        if self.tv_mat.identify_region(evento.x, evento.y) == "heading":
            return None
        return self.tv_mat.identify_row(evento.y) or None

    def receber(self, x_raiz, y_raiz, material):
        alvo = self.winfo_containing(x_raiz, y_raiz)
        for nome, tv in self.grades.items():
            if alvo is tv:
                self._soltar_na_grade(nome, tv, x_raiz, y_raiz, material)
                return
        self.barra.config(text="solte sobre uma celula de peca")

    def _soltar_na_grade(self, nome, tv, x_raiz, y_raiz, material):
        x = x_raiz - tv.winfo_rootx()
        y = y_raiz - tv.winfo_rooty()
        iid = tv.identify_row(y)
        col = tv.identify_column(x)
        if not iid or not col:
            return
        g = self.cfg["grupos"][nome]
        deslocamento = 2 if nome == "corpo" else 1
        idx_col = int(col[1:]) - 1 - deslocamento
        if idx_col < 0:
            self.barra.config(text="essa coluna nao e de material")
            return
        if idx_col >= len(g["pecas"]):
            return
        self._ajustar(g)
        g["variacoes"][int(iid)]["materiais"][idx_col] = material
        self.redesenhar_grade(nome)
        self.barra.config(text="%s  ->  %s / %s" % (
            material, nome, nucleo.nome_peca(g, idx_col)))

    def _ajustar(self, g):
        n = len(g["pecas"])
        for var in g["variacoes"]:
            mats = var.setdefault("materiais", [])
            while len(mats) < n:
                mats.append(None)
            del mats[n:]

    # ------------------------------------------------------------ grades

    def redesenhar_materiais(self):
        self.tv_mat.delete(*self.tv_mat.get_children())
        self.amostras.clear()
        if not self.insp:
            return
        for m in self.insp["materiais"]:
            img = amostra(m.get("cor"))
            self.amostras[m["nome"]] = img
            self.tv_mat.insert("", "end", iid=m["nome"], text="  " + m["nome"],
                               image=img)

    def redesenhar_grade(self, nome):
        g = self.cfg["grupos"][nome]
        self._ajustar(g)
        tv = self.grades[nome]
        pecas = g["pecas"]

        if nome == "corpo":
            cols, titulos, larguras = ["numero", "nome"], ["n", "nome"], [50, 130]
        else:
            cols, titulos, larguras = ["nome"], ["nome da pasta"], [180]
        for i in range(len(pecas)):
            cols.append("p%d" % i)
            titulos.append(nucleo.nome_peca(g, i))
            larguras.append(140)

        tv["columns"] = cols
        for c, t, w in zip(cols, titulos, larguras):
            tv.heading(c, text=t)
            tv.column(c, width=w, anchor="w", stretch=False)

        tv.delete(*tv.get_children())
        for i, var in enumerate(g["variacoes"]):
            vals = []
            if nome == "corpo":
                vals.append(var.get("numero", ""))
            vals.append(var.get("nome", ""))
            for j in range(len(pecas)):
                vals.append(var["materiais"][j] or VAZIO)
            tv.insert("", "end", iid=str(i), values=vals)
        self.redesenhar_selecao()

    def peca_nova(self, nome):
        g = self.cfg["grupos"][nome]
        g["pecas"].append("peca %d" % (len(g["pecas"]) + 1))
        self.redesenhar_grade(nome)

    def peca_renomear(self, nome):
        g = self.cfg["grupos"][nome]
        if not g["pecas"]:
            self.barra.config(text="nao ha peca para renomear")
            return
        janela = Escolha(self, "Renomear qual peca?", g["pecas"])
        self.wait_window(janela)
        if janela.indice is None:
            return
        novo = Texto(self, "Nome da peca", g["pecas"][janela.indice])
        self.wait_window(novo)
        if novo.valor:
            g["pecas"][janela.indice] = novo.valor
            self.redesenhar_grade(nome)

    def peca_remover(self, nome):
        g = self.cfg["grupos"][nome]
        if not g["pecas"]:
            return
        janela = Escolha(self, "Remover qual peca?", g["pecas"])
        self.wait_window(janela)
        if janela.indice is None:
            return
        i = janela.indice
        del g["pecas"][i]
        for var in g["variacoes"]:
            if i < len(var.get("materiais", [])):
                del var["materiais"][i]
        self.redesenhar_grade(nome)

    def variacao_nova(self, nome):
        g = self.cfg["grupos"][nome]
        item = {"nome": "nova %d" % (len(g["variacoes"]) + 1),
                "materiais": [None] * len(g["pecas"])}
        if nome == "corpo":
            item["numero"] = "%02d" % (int(self.cfg.get("numero_inicial") or 2)
                                       + len(g["variacoes"]))
        g["variacoes"].append(item)
        self.redesenhar_grade(nome)

    def variacao_remover(self, nome):
        sel = self.grades[nome].selection()
        if not sel:
            self.barra.config(text="selecione uma linha da grade primeiro")
            return
        del self.cfg["grupos"][nome]["variacoes"][int(sel[0])]
        self.redesenhar_grade(nome)

    def variacao_mover(self, nome, passo):
        sel = self.grades[nome].selection()
        if not sel:
            self.barra.config(text="selecione uma linha da grade primeiro")
            return
        vs = self.cfg["grupos"][nome]["variacoes"]
        i = int(sel[0])
        j = i + passo
        if not (0 <= j < len(vs)):
            return
        vs[i], vs[j] = vs[j], vs[i]
        self.redesenhar_grade(nome)
        self.grades[nome].selection_set(str(j))

    def renumerar(self):
        nucleo.renumerar(self.cfg["grupos"]["corpo"],
                         int(self.cfg.get("numero_inicial") or 2))
        self.redesenhar_grade("corpo")

    def _duplo(self, evento, nome):
        tv = self.grades[nome]
        iid = tv.identify_row(evento.y)
        col = tv.identify_column(evento.x)
        if not iid or not col:
            return
        g = self.cfg["grupos"][nome]
        var = g["variacoes"][int(iid)]
        pos = int(col[1:]) - 1
        deslocamento = 2 if nome == "corpo" else 1

        if pos < deslocamento:
            campo = "numero" if (nome == "corpo" and pos == 0) else "nome"
            janela = Texto(self, "Editar %s" % campo, var.get(campo, ""))
            self.wait_window(janela)
            if janela.valor is not None:
                var[campo] = janela.valor
                self.redesenhar_grade(nome)
            return

        idx = pos - deslocamento
        if idx < len(g["pecas"]):
            self._ajustar(g)
            var["materiais"][idx] = None
            self.redesenhar_grade(nome)

    # ----------------------------------------------------------- cameras

    def redesenhar_cameras(self):
        self.rol_cam.limpar()
        self.cam_linhas = []
        lentes = {}
        if self.insp:
            lentes = {c["nome"]: c["lente"] for c in self.insp.get("cameras", [])}

        for i, c in enumerate(self.cfg.get("cameras", [])):
            linha = ttk.Frame(self.rol_cam.interno)
            linha.grid(row=i, column=0, sticky="w", pady=1)
            v_ativa = tk.BooleanVar(value=bool(c.get("ativa", True)))
            v_rot = tk.StringVar(value=c.get("rotulo", ""))
            ttk.Checkbutton(linha, variable=v_ativa,
                            command=self._cameras_mudaram).pack(side="left", padx=(6, 18))
            ttk.Label(linha, text=c["objeto"], width=30,
                      font=("Consolas", 9)).pack(side="left")
            e = ttk.Entry(linha, textvariable=v_rot, width=20)
            e.pack(side="left", padx=(0, 12))
            v_rot.trace_add("write", lambda *a: self._cameras_mudaram())
            ttk.Label(linha, text="%s mm" % lentes.get(c["objeto"], "?"),
                      foreground="#888").pack(side="left")
            self.cam_linhas.append({"objeto": c["objeto"], "ativa": v_ativa,
                                    "rotulo": v_rot})
        self.rol_cam._recalcular()

    def _cameras_mudaram(self):
        for linha, c in zip(self.cam_linhas, self.cfg.get("cameras", [])):
            c["ativa"] = linha["ativa"].get()
            texto = linha["rotulo"].get().strip()
            if texto:
                c["rotulo"] = texto
        self.recontar()
        self._atualizar_previa()

    def redesenhar_mascara(self):
        self.rol_masc.limpar()
        self.masc_vars = {}
        if not self.insp:
            return
        marcados = set((self.cfg.get("mascara") or {}).get("objetos") or [])
        for i, o in enumerate(self.insp["objetos"]):
            v = tk.BooleanVar(value=o["nome"] in marcados)
            self.masc_vars[o["nome"]] = v
            texto = "%s      %d faces%s" % (
                o["nome"], o["faces"], "   (oculto no arquivo)" if o["oculto"] else "")
            ttk.Checkbutton(self.rol_masc.interno, text=texto, variable=v,
                            command=self.recontar).grid(row=i, column=0,
                                                        sticky="w", pady=1)
        self.rol_masc._recalcular()

    # ---------------------------------------------------------- inspecao

    def inspecionar(self):
        self._colher()
        if not self.cfg.get("blend"):
            messagebox.showwarning("Falta o arquivo", "Escolha um .blend primeiro.")
            return
        self.barra.config(text="inspecionando...")
        self.update_idletasks()
        try:
            self.insp = nucleo.inspecionar(self.cfg["blend"], self.cfg.get("blender"))
        except Exception as e:
            messagebox.showerror("Inspecao", str(e))
            self.barra.config(text="a inspecao falhou")
            return

        self.materiais = [m["nome"] for m in self.insp["materiais"]]
        self.objetos = [o["nome"] for o in self.insp["objetos"]]
        self.redesenhar_materiais()
        self.redesenhar_mascara()
        nucleo.sincronizar_cameras(self.cfg, self.insp)
        self.redesenhar_cameras()

        c = self.insp.get("cycles") or {}
        self.rotulo_insp.config(
            text="%d materiais, %d cameras, %s %s samples" % (
                len(self.insp["materiais"]), len(self.insp["cameras"]),
                self.insp["engine"], c.get("samples", "?")),
            foreground="#0a7a3a")
        self.barra.config(text="inspecao concluida")
        self.redesenhar_grade("capinha")
        self.redesenhar_grade("corpo")
        self._atualizar_previa()

    # ----------------------------------------------------------- selecao

    def redesenhar_selecao(self):
        for chave in ("capinha", "corpo"):
            rol = self.rol_sel[chave]
            rol.limpar()
            self.sel_vars[chave] = []
            for i, var in enumerate(self.cfg["grupos"][chave]["variacoes"]):
                v = tk.BooleanVar(value=var.get("_sel", True))
                self.sel_vars[chave].append(v)
                cheios = sum(1 for m in var.get("materiais", []) if m)
                prefixo = ("%s  " % var.get("numero", "")) if chave == "corpo" else ""
                ttk.Checkbutton(
                    rol.interno,
                    text="%s%s      %d pecas" % (prefixo, var.get("nome", ""), cheios),
                    variable=v, command=self._selecao_mudou).grid(
                    row=i, column=0, sticky="w", pady=1)
            rol._recalcular()
        self.recontar()

    def _selecao_mudou(self):
        for chave in ("capinha", "corpo"):
            for v, var in zip(self.sel_vars[chave],
                              self.cfg["grupos"][chave]["variacoes"]):
                var["_sel"] = v.get()
        self.recontar()

    def _selecionados(self, chave):
        return [v.get("nome") for v in self.cfg["grupos"][chave]["variacoes"]
                if v.get("_sel", True)]

    def _plano(self):
        self._colher()
        return nucleo.montar_fila(
            self.cfg, self.insp,
            sel_capinha=self._selecionados("capinha"),
            sel_corpo=self._selecionados("corpo"),
            preview=(self.v_modo.get() == "preview"),
            forcar=self.v_forcar.get())

    def recontar(self):
        if not self.insp:
            self.rotulo_conta.config(text="inspecione o .blend")
            return
        try:
            plano = self._plano()
        except Exception as e:
            self.rotulo_conta.config(text=str(e)[:70])
            return
        seg = 16 if self.v_modo.get() == "final" else 3
        pendentes = sum(1 for j in plano["jobs"]
                        if self.v_forcar.get() or not os.path.exists(j["saida"]))
        minutos = max(1, round(pendentes * seg / 60)) if pendentes else 0
        self.rotulo_conta.config(
            text="%d renders  (%d a fazer, ~%d min)  +%d copias"
                 % (len(plano["jobs"]), pendentes, minutos, len(plano["copias"])))

    # ------------------------------------------------------------ acoes

    def conferir(self):
        if not self.insp:
            messagebox.showwarning("Falta inspecionar", "Inspecione o .blend primeiro.")
            return False
        self._colher()
        erros, avisos = nucleo.conferir(self.cfg, self.insp)
        self.log.delete("1.0", "end")
        if not erros and not avisos:
            self.escrever("tudo certo, nada a corrigir", "ok")
        for e in erros:
            self.escrever("ERRO   " + e, "erro")
        for a in avisos:
            self.escrever("aviso  " + a, "info")
        self.abas.select(3)
        return not erros

    def dry_run(self):
        if not self.conferir():
            return
        plano = self._plano()
        self.escrever("")
        self.escrever("%d renders + %d copias de mascara"
                      % (len(plano["jobs"]), len(plano["copias"])), "info")
        for j in plano["jobs"]:
            existe = os.path.exists(j["saida"])
            marca = "pula " if existe and not plano["forcar"] else "faz  "
            self.escrever("%s %s" % (marca, j["saida"]),
                          "info" if existe else None)
        for _, destino in plano["copias"]:
            self.escrever("copia %s" % destino, "info")

    def renderizar(self):
        if self.processo is not None:
            return
        if not self.conferir():
            return
        plano = self._plano()
        if not plano["jobs"]:
            self.escrever("nada a fazer", "info")
            return

        os.makedirs(PASTA_PROJETOS, exist_ok=True)
        caminho = os.path.join(PASTA_PROJETOS, "_fila.json")
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(plano, f, ensure_ascii=False, indent=1)

        try:
            cmd = nucleo.comando_render(self.cfg, caminho)
        except Exception as e:
            messagebox.showerror("Render", str(e))
            return

        self.copias_pendentes = plano["copias"]
        self.progresso.config(maximum=len(plano["jobs"]), value=0)
        self.log.delete("1.0", "end")
        self.escrever("%d jobs, modo %s" % (len(plano["jobs"]), self.v_modo.get()),
                      "info")
        self.botao_render.config(state="disabled")
        self.botao_parar.config(state="normal")

        self.processo = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            startupinfo=nucleo.sem_janela())
        threading.Thread(target=self._ler, args=(self.processo,),
                         daemon=True).start()

    def _ler(self, proc):
        for linha in proc.stdout:
            if linha.startswith("LOTE|"):
                self.linhas.put(linha[5:].strip())
        proc.wait()
        self.linhas.put("__FIM__")

    def _drenar(self):
        try:
            while True:
                linha = self.linhas.get_nowait()
                if linha == "__FIM__":
                    self._terminou()
                else:
                    self._mostrar(linha)
        except queue.Empty:
            pass
        self.after(120, self._drenar)

    def _mostrar(self, linha):
        if linha.startswith("OK "):
            self.progresso.step(1)
            self.escrever(linha, "ok")
        elif linha.startswith("PULADO"):
            self.progresso.step(1)
            self.escrever(linha, "info")
        elif linha.startswith("FALHA") or linha.startswith("ERRO"):
            self.escrever(linha, "erro")
        elif linha.startswith("INICIO"):
            self.barra.config(text=linha)
        else:
            self.escrever(linha, "info")

    def _terminou(self):
        self.processo = None
        self.botao_render.config(state="normal")
        self.botao_parar.config(state="disabled")
        feitas = 0
        for origem, destino in self.copias_pendentes:
            try:
                if os.path.exists(origem):
                    pasta = os.path.dirname(destino)
                    if pasta:
                        os.makedirs(pasta, exist_ok=True)
                    shutil.copy2(origem, destino)
                    feitas += 1
            except Exception as e:
                self.escrever("falha ao copiar mascara: %s" % e, "erro")
        if feitas:
            self.escrever("%d mascaras copiadas" % feitas, "ok")
        self.copias_pendentes = []
        self.barra.config(text="lote encerrado")
        self.recontar()

    def parar(self):
        if self.processo is not None:
            self.processo.terminate()
            self.escrever("interrompido pelo usuario", "erro")

    # ----------------------------------------------------------- projeto

    def _colher(self):
        if self.carregando:
            return
        self.cfg["blend"] = self.v_blend.get().strip()
        self.cfg["blender"] = self.v_exe.get().strip()
        self.cfg["raiz"] = self.v_raiz.get().strip()
        self.cfg["template"] = self.v_template.get().strip()
        self.cfg["tokens"] = {"aparelho": self.v_aparelho.get().strip(),
                              "linha": self.v_linha.get().strip()}

        def num(var, padrao):
            try:
                return int(var.get())
            except (ValueError, tk.TclError):
                return padrao

        self.cfg["qualidade"] = {"samples": num(self.v_samples, 256),
                                 "resolucao": num(self.v_res, 1000),
                                 "gpu": self.v_gpu.get()}
        self.cfg["preview"] = {"samples": num(self.v_psamples, 32),
                               "resolucao": num(self.v_pres, 500),
                               "gpu": self.v_gpu.get()}

        antes = self.cfg.get("mascara") or {}
        if self.masc_vars:
            objetos = [n for n, v in self.masc_vars.items() if v.get()]
        else:
            # lista ainda nao populada (sem inspecao): preserva a escolha
            # do projeto salvo em vez de apagar
            objetos = antes.get("objetos") or []
        self.cfg["mascara"] = {"ativa": self.v_masc.get(), "objetos": objetos,
                               "numero": self.v_masc_num.get().strip() or "01",
                               "samples": num(self.v_masc_spp, 8)}

    def _espalhar(self):
        self.carregando = True
        try:
            self._espalhar_campos()
        finally:
            self.carregando = False
        self.redesenhar_grade("capinha")
        self.redesenhar_grade("corpo")
        self.redesenhar_cameras()
        self.redesenhar_mascara()
        self._atualizar_previa()

    def _espalhar_campos(self):
        self.v_blend.set(self.cfg.get("blend", ""))
        self.v_exe.set(self.cfg.get("blender") or nucleo.achar_blender() or "")
        self.v_raiz.set(self.cfg.get("raiz", ""))
        self.v_template.set(self.cfg.get("template", ""))
        t = self.cfg.get("tokens") or {}
        self.v_aparelho.set(t.get("aparelho", ""))
        self.v_linha.set(t.get("linha", ""))
        q = self.cfg.get("qualidade") or {}
        self.v_samples.set(str(q.get("samples", 256)))
        self.v_res.set(str(q.get("resolucao", 1000)))
        self.v_gpu.set(bool(q.get("gpu", True)))
        p = self.cfg.get("preview") or {}
        self.v_psamples.set(str(p.get("samples", 32)))
        self.v_pres.set(str(p.get("resolucao", 500)))
        m = self.cfg.get("mascara") or {}
        self.v_masc.set(bool(m.get("ativa", True)))
        self.v_masc_num.set(m.get("numero", "01"))
        self.v_masc_spp.set(str(m.get("samples", 8)))

    def projeto_novo(self):
        self.cfg = nucleo.config_novo()
        self.insp = None
        self.caminho_cfg = None
        self.materiais = []
        self.objetos = []
        self.tv_mat.delete(*self.tv_mat.get_children())
        self.rotulo_projeto.config(text="projeto novo")
        self.rotulo_insp.config(text="nao inspecionado", foreground="#888")
        self._espalhar()

    def projeto_abrir(self):
        c = filedialog.askopenfilename(initialdir=PASTA_PROJETOS,
                                       filetypes=[("Projeto", "*.json")])
        if not c:
            return
        try:
            self.cfg = nucleo.carregar_config(c)
        except Exception as e:
            messagebox.showerror("Abrir", str(e))
            return
        self.caminho_cfg = c
        self.rotulo_projeto.config(text=os.path.basename(c))
        self._espalhar()
        if os.path.exists(self.cfg.get("blend") or ""):
            self.inspecionar()

    def projeto_salvar(self):
        self._colher()
        c = self.caminho_cfg
        if not c:
            c = filedialog.asksaveasfilename(
                initialdir=PASTA_PROJETOS, defaultextension=".json",
                filetypes=[("Projeto", "*.json")])
            if not c:
                return
        limpo = json.loads(json.dumps(self.cfg))
        for g in limpo["grupos"].values():
            for var in g["variacoes"]:
                var.pop("_sel", None)
        nucleo.salvar_config(limpo, c)
        self.caminho_cfg = c
        self.rotulo_projeto.config(text=os.path.basename(c))
        self.barra.config(text="salvo em %s" % c)

    def _fechar(self):
        if self.processo is not None:
            if not messagebox.askyesno("Sair", "Ha um lote rodando. Interromper?"):
                return
            self.processo.terminate()
        self.destroy()


# --------------------------------------------------------------- dialogos

class Texto(tk.Toplevel):
    def __init__(self, pai, titulo, inicial=""):
        super().__init__(pai)
        self.title(titulo)
        self.valor = None
        self.resizable(False, False)
        self.transient(pai)
        quadro = ttk.Frame(self, padding=12)
        quadro.pack()
        self.var = tk.StringVar(value=inicial or "")
        entrada = ttk.Entry(quadro, textvariable=self.var, width=42)
        entrada.pack()
        entrada.focus_set()
        entrada.select_range(0, "end")
        entrada.bind("<Return>", lambda e: self.ok())
        entrada.bind("<Escape>", lambda e: self.destroy())
        barra = ttk.Frame(quadro)
        barra.pack(fill="x", pady=(10, 0))
        ttk.Button(barra, text="Ok", command=self.ok).pack(side="right")
        ttk.Button(barra, text="Cancelar", command=self.destroy).pack(side="right", padx=5)
        self.grab_set()

    def ok(self):
        self.valor = self.var.get().strip()
        self.destroy()


class Escolha(tk.Toplevel):
    def __init__(self, pai, titulo, itens):
        super().__init__(pai)
        self.title(titulo)
        self.indice = None
        self.transient(pai)
        quadro = ttk.Frame(self, padding=12)
        quadro.pack()
        self.lista = tk.Listbox(quadro, width=36,
                                height=min(10, max(3, len(itens))),
                                exportselection=False)
        for i in itens:
            self.lista.insert("end", i)
        self.lista.selection_set(0)
        self.lista.pack()
        self.lista.bind("<Double-1>", lambda e: self.ok())
        barra = ttk.Frame(quadro)
        barra.pack(fill="x", pady=(10, 0))
        ttk.Button(barra, text="Ok", command=self.ok).pack(side="right")
        ttk.Button(barra, text="Cancelar", command=self.destroy).pack(side="right", padx=5)
        self.grab_set()

    def ok(self):
        sel = self.lista.curselection()
        self.indice = sel[0] if sel else None
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
