"""Dialogo nativo de escolher arquivo/pasta, para uso pelo servidor web.

Roda como processo separado e curto, porque o navegador nao entrega
caminho de sistema para o backend. Imprime o caminho escolhido, ou nada
se o usuario cancelar.

    python dialogo.py blend|exe|pasta
"""

import sys
import tkinter as tk
from tkinter import filedialog


def main():
    modo = sys.argv[1] if len(sys.argv) > 1 else "pasta"

    raiz = tk.Tk()
    raiz.withdraw()
    try:
        raiz.attributes("-topmost", True)
    except tk.TclError:
        pass

    if modo == "blend":
        caminho = filedialog.askopenfilename(
            title="Escolha o arquivo .blend",
            filetypes=[("Blender", "*.blend"), ("Todos", "*.*")])
    elif modo == "exe":
        caminho = filedialog.askopenfilename(
            title="Escolha o blender.exe",
            filetypes=[("Executavel", "*.exe"), ("Todos", "*.*")])
    else:
        caminho = filedialog.askdirectory(title="Escolha a pasta")

    raiz.destroy()
    sys.stdout.write(caminho or "")


main()
