"""Windows desktop UI for exact duplicates, face groups and reversible albums."""
from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageDraw, ImageOps, ImageTk

from core import move_to_album, quarantine, scan, undo_last
from faces import merge_groups, regroup_after_naming, save_name, scan_faces, split_group
from settings import load_settings, save_settings
from updater import VERSION, check_for_update, launch_installer, stage_update


BG = "#0B1220"
PANEL = "#142235"
RAISED = "#1C2F45"
TEXT = "#F1F6F5"
MUTED = "#AABBC6"
ACCENT = "#43D6A4"
SELECT = "#285D60"


class FotosClaras(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Fotos Claras · ordenar tus recuerdos")
        self.geometry("1260x830")
        self.minsize(980, 670)
        self.configure(bg=BG)
        self.settings = load_settings()
        self._resuming = False
        self.folder = None
        self.photos, self.groups, self.versions = [], [], []
        self.people, self.no_faces, self.face_counts = [], [], {}
        self.filtered_paths = []
        self.events = queue.Queue()
        self.busy = False
        self.updating = False
        self.rescan_faces = False
        self._style()
        self._set_icon()
        self._layout()
        self.count_choice.set(self.settings["count_filter"])
        self.tabs.select(self.settings["last_tab"])
        self._update_navigation()
        self.tabs.bind("<<NotebookTabChanged>>", self._remember_tab)
        previous_folder = Path(self.settings["last_folder"])
        if self.settings["last_folder"] and previous_folder.is_dir():
            self.folder = str(previous_folder)
            self.folder_label.config(text=f"CARPETA ACTUAL   {self.folder}")
            self.analyze_button.config(state="normal")
            self.rescan_faces = self.settings["faces_analyzed"]
            self._resuming = True
            self.after(350, self.analyze)
        self.after(100, self._poll)
        self.after(4500, self.check_updates)

    def _style(self):
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 10))
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Segoe UI Semibold", 27))
        style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 10))
        style.configure("Status.TLabel", background=BG, foreground=ACCENT, font=("Segoe UI Semibold", 10))
        style.configure("Section.TLabel", background=BG, foreground=TEXT, font=("Segoe UI Semibold", 12))
        style.configure("Preview.TLabel", background=PANEL, foreground=MUTED, font=("Segoe UI", 10))
        style.configure("TButton", background=RAISED, foreground=TEXT, padding=(15, 10),
                        font=("Segoe UI Semibold", 10), borderwidth=0, relief="flat", focuscolor=RAISED)
        style.map("TButton", background=[("active", "#2B445C"), ("pressed", SELECT), ("disabled", PANEL)],
                  foreground=[("disabled", "#6E8394")])
        style.configure("Accent.TButton", background=ACCENT, foreground=BG, padding=(17, 11))
        style.map("Accent.TButton", background=[("active", "#70E4BC"), ("pressed", "#2FBC8F"), ("disabled", PANEL)],
                  foreground=[("disabled", "#6E8394")])
        style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 5, 0, 0))
        style.configure("TNotebook.Tab", background=PANEL, foreground=MUTED, padding=(17, 12),
                        font=("Segoe UI Semibold", 10), borderwidth=0)
        style.map("TNotebook.Tab", background=[("selected", SELECT), ("active", RAISED)],
                  foreground=[("selected", TEXT), ("active", TEXT)])
        style.configure("Hidden.TNotebook", background=BG, borderwidth=0)
        style.layout("Hidden.TNotebook.Tab", [])
        style.layout("TNotebook.Tab", [])
        style.configure("Nav.TButton", background=BG, foreground=MUTED, padding=(16, 14),
                        anchor="w", font=("Segoe UI Semibold", 10))
        style.map("Nav.TButton", background=[("active", RAISED)], foreground=[("active", TEXT)])
        style.configure("Active.Nav.TButton", background=SELECT, foreground=TEXT, padding=(16, 14),
                        anchor="w", font=("Segoe UI Semibold", 10))
        style.map("Active.Nav.TButton", background=[("active", SELECT)])
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT,
                        rowheight=38, borderwidth=0, relief="flat", font=("Segoe UI", 10))
        style.map("Treeview", background=[("selected", SELECT)], foreground=[("selected", TEXT)])
        style.configure("Treeview.Heading", background=RAISED, foreground=MUTED,
                        font=("Segoe UI Semibold", 10), padding=(10, 9), relief="flat")
        style.map("Treeview.Heading", background=[("active", SELECT)])
        style.configure("TPanedwindow", background=BG, sashwidth=8, sashrelief="flat")
        style.configure("TCombobox", fieldbackground=PANEL, background=PANEL, foreground=TEXT,
                        arrowcolor=ACCENT, padding=7, borderwidth=0)
        style.map("TCombobox", fieldbackground=[("readonly", PANEL)], foreground=[("readonly", TEXT)])
        style.configure("TEntry", fieldbackground=PANEL, foreground=TEXT, insertcolor=TEXT,
                        borderwidth=0, padding=9)
        style.configure("Horizontal.TProgressbar", troughcolor=PANEL, background=ACCENT,
                        borderwidth=0, thickness=7)
        style.configure("TScrollbar", background=RAISED, troughcolor=PANEL, borderwidth=0,
                        arrowcolor=MUTED)
        self.option_add("*TCombobox*Listbox.background", PANEL)
        self.option_add("*TCombobox*Listbox.foreground", TEXT)

    def _set_icon(self):
        icon = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(icon)
        draw.rounded_rectangle((3, 3, 61, 61), radius=15, fill=ACCENT)
        draw.rounded_rectangle((13, 17, 50, 47), radius=5, fill=BG)
        draw.ellipse((37, 22, 44, 29), fill=ACCENT)
        draw.polygon(((17, 42), (28, 31), (34, 37), (39, 33), (48, 43)), fill=ACCENT)
        self._app_icon = ImageTk.PhotoImage(icon)
        self.iconphoto(True, self._app_icon)

    def _layout(self):
        top = ttk.Frame(self, padding=(24, 19, 24, 10))
        top.pack(fill="x")
        ttk.Label(top, text=f"◆  Fotos Claras  ·  v{VERSION}", style="Title.TLabel").pack(anchor="w")
        ttk.Label(top, text="Tus recuerdos, ordenados a tu manera. Siempre decidís qué fotos mover.",
                  style="Muted.TLabel").pack(anchor="w", pady=(2, 2))
        buttons = ttk.Frame(top)
        buttons.pack(fill="x", pady=(17, 12))
        ttk.Button(buttons, text="Elegir carpeta", command=self.choose_folder).pack(side="left", padx=(0, 8))
        self.analyze_button = ttk.Button(buttons, text="Buscar fotos", command=self.analyze, state="disabled")
        self.analyze_button.pack(side="left", padx=(0, 8))
        self.face_button = ttk.Button(buttons, text="Buscar rostros", command=self.analyze_faces,
                                      style="Accent.TButton", state="disabled")
        self.face_button.pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Deshacer último movimiento", command=self.undo).pack(side="right")
        ttk.Button(buttons, text="Buscar actualizaciones", command=lambda: self.check_updates(manual=True)).pack(side="right", padx=(0, 8))
        self.folder_label = ttk.Label(top, text="CARPETA ACTUAL   Elegí dónde están tus fotos", style="Muted.TLabel")
        self.folder_label.pack(anchor="w")
        self.progress = ttk.Progressbar(top, maximum=100)
        self.progress.pack(fill="x", pady=(11, 5))
        self.status = ttk.Label(top, text="Lista para empezar", style="Status.TLabel")
        self.status.pack(anchor="w")

        workspace = ttk.Frame(self, padding=(24, 8, 24, 20))
        workspace.pack(fill="both", expand=True)
        sidebar = ttk.Frame(workspace, width=220)
        sidebar.pack(side="left", fill="y", padx=(0, 17))
        sidebar.pack_propagate(False)
        ttk.Label(sidebar, text="EXPLORAR", style="Muted.TLabel").pack(anchor="w", padx=13, pady=(10, 13))
        self.nav_buttons = []
        nav_items = ("▦   Duplicados exactos", "◇   Versiones para revisar", "▧   Todas las fotos",
                     "◉   Personas", "▥   Cantidad de rostros", "○   Sin rostros")
        for index, title in enumerate(nav_items):
            button = ttk.Button(sidebar, text=title, style="Nav.TButton",
                                command=lambda selected=index: self.tabs.select(selected))
            button.pack(fill="x", pady=3)
            self.nav_buttons.append(button)
        ttk.Label(sidebar, text="LOCAL Y PRIVADO\nLas fotos se analizan\nen tu computadora.",
                  style="Muted.TLabel", justify="left").pack(side="bottom", anchor="w", padx=13, pady=12)
        content = ttk.Frame(workspace)
        content.pack(side="left", fill="both", expand=True)
        self.tabs = ttk.Notebook(content, style="Hidden.TNotebook")
        self.tabs.pack(fill="both", expand=True)
        exact, versions, all_tab, people, counts, none = [ttk.Frame(self.tabs, padding=(13, 18)) for _ in range(6)]
        for tab, title in zip((exact, versions, all_tab, people, counts, none),
                              ("Duplicados exactos", "Versiones por revisar", "Todas las fotos", "Personas", "Por cantidad de rostros", "Sin rostros")):
            self.tabs.add(tab, text=title)
        self._group_tab(exact, exact=True)
        self._group_tab(versions, exact=False)
        self._all_tab(all_tab)
        self._people_tab(people)
        self._counts_tab(counts)
        self._no_faces_tab(none)
        self._update_navigation()

    def _update_navigation(self):
        current = self.tabs.index(self.tabs.select())
        for index, button in enumerate(self.nav_buttons):
            button.configure(style="Active.Nav.TButton" if index == current else "Nav.TButton")

    def _list(self, parent, callback, multiple=True):
        box = tk.Listbox(parent, selectmode="extended" if multiple else "browse", exportselection=False,
                         font=("Segoe UI", 10), activestyle="none", bg=PANEL, fg=TEXT,
                         selectbackground=SELECT, selectforeground=TEXT, highlightthickness=0,
                         relief="flat", borderwidth=0,
                         selectborderwidth=0)
        box.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(parent, command=box.yview)
        scroll.pack(side="left", fill="y")
        box.configure(yscrollcommand=scroll.set)
        box.bind("<<ListboxSelect>>", callback)
        return box

    def _group_tab(self, tab, exact):
        prefix = "exact" if exact else "version"
        message = ("Mismos píxeles, aunque cambie el nombre o formato. El primer archivo es la sugerencia para conservar."
                   if exact else "Posibles versiones recomprimidas de una foto. Pueden ser tomas distintas: compará y elegí manualmente.")
        ttk.Label(tab, text=message, wraplength=1050, style="Muted.TLabel").pack(anchor="w", pady=(0, 13))
        panes = ttk.Panedwindow(tab, orient="horizontal")
        panes.pack(fill="both", expand=True)
        left, middle, right = (ttk.Frame(panes) for _ in range(3))
        for frame, weight in ((left, 2), (middle, 3), (right, 3)):
            panes.add(frame, weight=weight)
        tree = ttk.Treeview(left, columns=("count",), show="tree headings", selectmode="browse")
        tree.heading("#0", text="Grupo")
        tree.heading("count", text="Fotos")
        tree.column("#0", width=120)
        tree.column("count", width=60, anchor="center")
        tree.pack(fill="both", expand=True)
        tree.bind("<<TreeviewSelect>>", lambda event: self.show_group(exact))
        setattr(self, prefix + "_tree", tree)
        ttk.Label(middle, text="Archivos del grupo", style="Section.TLabel").pack(anchor="w")
        box_frame = ttk.Frame(middle)
        box_frame.pack(fill="both", expand=True, pady=5)
        box = self._list(box_frame, lambda event: self.show_group_file(exact))
        setattr(self, prefix + "_list", box)
        if exact:
            ttk.Button(middle, text="Marcar copias para apartar", command=self.mark_copies).pack(fill="x", pady=3)
            ttk.Label(middle, text="Marca todas menos la primera sugerida; comprobá la selección antes de mover.",
                      wraplength=300, style="Muted.TLabel").pack(anchor="w", pady=(3, 5))
        ttk.Button(middle, text="Mover las fotos marcadas a revisión", command=lambda: self.move_group(exact),
                   style="Accent.TButton").pack(fill="x", pady=4)
        preview = ttk.Label(right, text="Elegí un grupo", anchor="center", justify="center", style="Preview.TLabel")
        preview.pack(fill="both", expand=True, padx=9)
        setattr(self, prefix + "_preview", preview)
        detail = ttk.Label(right, text="", wraplength=310, style="Muted.TLabel")
        detail.pack(fill="x", padx=9, pady=5)
        setattr(self, prefix + "_details", detail)

    def _all_tab(self, tab):
        self.all_count = ttk.Label(tab, text="Todavía no se analizó ninguna carpeta")
        self.all_count.pack(anchor="w", pady=(0, 8))
        body = ttk.Frame(tab)
        body.pack(fill="both", expand=True)
        self.all_list = self._list(body, lambda event: self._preview_selection(self.all_list, [p.path for p in self.photos], self.all_preview))
        self.all_preview = ttk.Label(body, text="Elegí una foto", anchor="center", style="Preview.TLabel")
        self.all_preview.pack(side="left", fill="both", expand=True, padx=12)
        ttk.Button(tab, text="Mover seleccionadas a un álbum", style="Accent.TButton",
                   command=lambda: self.album_dialog([self.photos[i].path for i in self.all_list.curselection()])).pack(anchor="e", pady=9)

    def _people_tab(self, tab):
        ttk.Label(tab, text="Seleccioná una persona y mirá sus rostros. Escribí el nombre una vez: la app buscará más fotos de esa persona.",
                  wraplength=1050, style="Muted.TLabel").pack(anchor="w")
        ttk.Button(tab, text="¿Quién es esta persona? Poner nombre al grupo seleccionado",
                   command=self.name_person, style="Accent.TButton").pack(anchor="w", pady=(10, 5))
        ttk.Label(tab, text="Si ves a otra persona mezclada, marcá esas fotos y tocá «Separar fotos marcadas» antes de nombrar.",
                  wraplength=1050, style="Muted.TLabel").pack(anchor="w")
        body = ttk.Frame(tab)
        body.pack(fill="both", expand=True, pady=8)
        self.people_tree = ttk.Treeview(body, columns=("count",), show="tree headings", selectmode="browse")
        self.people_tree.heading("#0", text="Persona")
        self.people_tree.heading("count", text="Fotos")
        self.people_tree.column("#0", width=220)
        self.people_tree.column("count", width=60, anchor="center")
        self.people_tree.pack(side="left", fill="both", expand=True)
        self.people_tree.bind("<<TreeviewSelect>>", self.show_person)
        self.people_tree.bind("<Double-1>", lambda event: self.name_person())
        side = ttk.Frame(body, padding=(12, 0))
        side.pack(side="left", fill="both", expand=True)
        list_frame = ttk.Frame(side)
        list_frame.pack(fill="both", expand=True)
        self.person_list = self._list(list_frame, self.show_person_photo)
        ttk.Label(side, text="Rostro detectado").pack(anchor="w")
        self.person_preview = ttk.Label(side, text="Seleccioná una persona", anchor="center", style="Preview.TLabel")
        self.person_preview.pack(fill="both", expand=True)
        ttk.Label(side, text="Foto completa").pack(anchor="w")
        self.person_photo_preview = ttk.Label(side, text="", anchor="center", style="Preview.TLabel")
        self.person_photo_preview.pack(fill="both", expand=True)
        controls = ttk.Frame(tab)
        controls.pack(fill="x")
        for label, action in (("Separar fotos marcadas", self.split_person),
                              ("Unir con otra persona", self.merge_person), ("Mover fotos del grupo a álbum", self.move_person)):
            ttk.Button(controls, text=label, command=action).pack(side="left", padx=(0, 7))

    def _counts_tab(self, tab):
        ttk.Label(tab, text="Filtrá por cantidad de caras y por personas. Una foto con Santi y Dai aparece aunque haya otros.",
                  wraplength=1050, style="Muted.TLabel").pack(anchor="w", pady=(0, 11))
        filters = ttk.Frame(tab)
        filters.pack(fill="x")
        self.count_choice = ttk.Combobox(filters, state="readonly", width=16,
                                         values=("Todos", "0 rostros", "1 rostro", "2 rostros", "3 o más"))
        self.count_choice.set("Todos")
        self.count_choice.pack(side="left", padx=(0, 10))
        self.count_choice.bind("<<ComboboxSelected>>", self.update_filter)
        ttk.Label(filters, text="Personas que deben aparecer (Ctrl + clic para elegir varias):").pack(side="left")
        self.filter_people = tk.Listbox(filters, selectmode="extended", exportselection=False, height=4, width=28,
                                        bg=PANEL, fg=TEXT, selectbackground=SELECT, selectforeground=TEXT,
                                        highlightthickness=0, borderwidth=0, relief="flat", font=("Segoe UI", 10))
        self.filter_people.pack(side="left", padx=8)
        self.filter_people.bind("<<ListboxSelect>>", self.update_filter)
        ttk.Button(filters, text="Quitar filtro de personas", command=self.clear_person_filter).pack(side="left")
        self.filter_count = ttk.Label(tab, text="Primero buscá rostros")
        self.filter_count.pack(anchor="w", pady=5)
        body = ttk.Frame(tab)
        body.pack(fill="both", expand=True)
        self.filtered_list = self._list(body, lambda event: self._preview_selection(self.filtered_list, self.filtered_paths, self.filtered_preview))
        self.filtered_preview = ttk.Label(body, text="Elegí una foto", anchor="center", style="Preview.TLabel")
        self.filtered_preview.pack(side="left", fill="both", expand=True, padx=12)
        ttk.Button(tab, text="Mover seleccionadas a un álbum", style="Accent.TButton",
                   command=lambda: self.album_dialog([self.filtered_paths[i] for i in self.filtered_list.curselection()])).pack(anchor="e", pady=9)

    def _no_faces_tab(self, tab):
        ttk.Label(tab, text="Sin caras detectadas. Puede haber caras pequeñas, de perfil u ocultas; revisá antes de mover.",
                  wraplength=1050, style="Muted.TLabel").pack(anchor="w")
        body = ttk.Frame(tab)
        body.pack(fill="both", expand=True, pady=8)
        self.noface_list = self._list(body, lambda event: self._preview_selection(self.noface_list, self.no_faces, self.noface_preview))
        self.noface_preview = ttk.Label(body, text="Elegí una foto", anchor="center", style="Preview.TLabel")
        self.noface_preview.pack(side="left", fill="both", expand=True, padx=12)
        ttk.Button(tab, text="Mover seleccionadas a un álbum", style="Accent.TButton",
                   command=lambda: self.album_dialog([self.no_faces[i] for i in self.noface_list.curselection()])).pack(anchor="e", pady=9)

    def choose_folder(self):
        if self.busy:
            return
        chosen = filedialog.askdirectory(title="Elegí la carpeta con tus fotos")
        if chosen:
            self.folder = chosen
            self.folder_label.config(text=f"CARPETA ACTUAL   {chosen}")
            self.analyze_button.config(state="normal")
            self.rescan_faces = False
            self._resuming = False
            self.settings.update(last_folder=chosen, faces_analyzed=False,
                                 last_person_id="", last_tab=2)
            save_settings(self.settings)
            self.analyze()

    def _remember_tab(self, _=None):
        self._update_navigation()
        if not self._resuming:
            self.settings["last_tab"] = self.tabs.index(self.tabs.select())
            save_settings(self.settings)

    def _start(self, job, finished):
        if self.busy:
            return
        self.busy = True
        self.analyze_button.config(state="disabled")
        self.face_button.config(state="disabled")
        self.progress["value"] = 0
        self.status.config(text="Analizando... puede tardar con miles de fotos")
        def run():
            try:
                result = job(lambda done, total: self.events.put(("progress", done, total)))
                self.events.put(("done", finished, result))
            except Exception as error:
                self.events.put(("error", str(error)))
        threading.Thread(target=run, daemon=True).start()

    def _poll(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "progress":
                    _, done, total = event
                    self.progress["value"] = 100 * done / max(1, total)
                    self.status.config(text=f"Analizadas {done} de {total} fotos...")
                elif event[0] == "done":
                    self.busy = False
                    event[1](event[2])
                    self.analyze_button.config(state="normal" if self.folder else "disabled")
                    self.face_button.config(state="normal" if self.photos else "disabled")
                elif event[0] == "error":
                    self.busy = False
                    self._resuming = False
                    self.analyze_button.config(state="normal" if self.folder else "disabled")
                    self.face_button.config(state="normal" if self.photos else "disabled")
                    self.status.config(text="No se pudo terminar el análisis")
                    messagebox.showerror("No se pudo analizar", event[1])
                elif event[0] == "update_result":
                    _, manual, release, error = event
                    if error:
                        self.updating = False
                        if manual:
                            messagebox.showwarning("Actualizaciones", f"No pude consultar las versiones: {error}")
                    elif release:
                        self._offer_update(release)
                    else:
                        self.updating = False
                        if manual:
                            messagebox.showinfo("Actualizaciones", f"Fotos Claras v{VERSION} ya es la última versión.")
                elif event[0] == "update_staged":
                    _, error = event
                    if error:
                        self.updating = False
                        messagebox.showerror("Actualización", f"No pude descargar la actualización: {error}")
                    else:
                        try:
                            launch_installer(Path(__file__).resolve().parent)
                        except (OSError, ValueError) as failure:
                            self.updating = False
                            messagebox.showerror("Actualización", str(failure))
                        else:
                            self.destroy()
                            return
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def check_updates(self, manual=False):
        if self.updating:
            return
        if getattr(sys, "frozen", False):
            if manual:
                messagebox.showinfo("Actualizaciones", "Esta instalación en .exe necesita actualizarse desde un instalador. Abrí la versión con ABRIR.bat para usar las actualizaciones automáticas.")
            return
        self.updating = True
        def work():
            try:
                self.events.put(("update_result", manual, check_for_update(), None))
            except Exception as error:
                self.events.put(("update_result", manual, None, str(error)))
        threading.Thread(target=work, daemon=True).start()

    def _offer_update(self, release):
        if self.busy:
            self.after(500, lambda: self._offer_update(release))
            return
        if not messagebox.askyesno("Nueva versión", f"Está disponible Fotos Claras {release['version']}.\n\n¿Descargarla e instalarla ahora? La app se cerrará y volverá a abrirse. Tus fotos y nombres quedan guardados."):
            self.updating = False
            return
        self.status.config(text=f"Descargando Fotos Claras {release['version']}...")
        def work():
            try:
                stage_update(release, Path(__file__).resolve().parent)
                self.events.put(("update_staged", None))
            except Exception as error:
                self.events.put(("update_staged", str(error)))
        threading.Thread(target=work, daemon=True).start()

    def analyze(self):
        if self.folder:
            self._start(lambda progress: scan(self.folder, progress), self._scan_done)

    def _scan_done(self, result):
        self.photos, self.groups, self.versions, errors, extensions = result
        self.people, self.no_faces, self.face_counts = [], [], {}
        for tree in (self.exact_tree, self.version_tree, self.people_tree):
            tree.delete(*tree.get_children())
        for box in (self.exact_list, self.version_list, self.all_list, self.person_list,
                    self.noface_list, self.filtered_list, self.filter_people):
            box.delete(0, "end")
        self.all_count.config(text=f"{len(self.photos)} fotos leídas en esta carpeta y sus subcarpetas")
        for i in range(0, len(self.photos), 500):
            self.all_list.insert("end", *(str(Path(p.path).relative_to(self.folder)) for p in self.photos[i:i + 500]))
        for tree, groups in ((self.exact_tree, self.groups), (self.version_tree, self.versions)):
            for i, group in enumerate(groups):
                tree.insert("", "end", iid=str(i), text=f"Grupo {i+1}", values=(len(group),))
            if groups:
                tree.selection_set("0")
        if self.groups:
            self.show_group(True)
        if self.versions:
            self.show_group(False)
        self.status.config(text=f"{len(self.photos)} fotos · {len(self.groups)} grupos exactos · {len(self.versions)} posibles versiones · {len(errors)} errores")
        self.tabs.select(0 if self.groups else 1 if self.versions else 2)
        if self.rescan_faces and self.photos:
            self.rescan_faces = False
            self.after(120, self.analyze_faces)
        elif self._resuming:
            self.tabs.select(self.settings["last_tab"])
            self._resuming = False
        elif not self.photos:
            examples = "\n".join(f"{Path(path).name}: {reason}" for path, reason in errors[:3])
            messagebox.showinfo("Fotos", f"Encontré {sum(extensions.values())} archivos de imagen y leí {len(self.photos)}.\n{examples}")
        elif errors:
            messagebox.showwarning("Algunos archivos no se pudieron leer", f"Leí {len(self.photos)} fotos y omití {len(errors)}.\n{errors[0][0]}: {errors[0][1]}")

    def show_group(self, exact):
        tree, box = (self.exact_tree, self.exact_list) if exact else (self.version_tree, self.version_list)
        groups = self.groups if exact else self.versions
        box.delete(0, "end")
        selection = tree.selection()
        if not selection:
            return
        group = groups[int(selection[0])]
        for i, photo in enumerate(group):
            role = "★ Sugerida para conservar" if exact and i == 0 else "Foto"
            box.insert("end", f"{role} · {Path(photo.path).name} · {photo.width}×{photo.height}")
        self._show_group_photo(group[0], exact)

    def show_group_file(self, exact):
        tree, box = (self.exact_tree, self.exact_list) if exact else (self.version_tree, self.version_list)
        selection, chosen = tree.selection(), box.curselection()
        if selection and chosen:
            self._show_group_photo((self.groups if exact else self.versions)[int(selection[0])][chosen[-1]], exact)

    def _show_group_photo(self, photo, exact):
        preview = self.exact_preview if exact else self.version_preview
        details = self.exact_details if exact else self.version_details
        self._show_preview(photo.path, preview)
        details.config(text=f"{photo.path}\n{photo.width} × {photo.height} píxeles · {photo.size / 1048576:.1f} MB")

    def _show_preview(self, path, label, enlarge=False):
        try:
            with Image.open(path) as source:
                image = ImageOps.exif_transpose(source)
                image.thumbnail((390, 310))
                if enlarge and max(image.size) < 220:
                    factor = 220 / max(image.size)
                    image = image.resize((round(image.width * factor), round(image.height * factor)), Image.Resampling.LANCZOS)
                preview = ImageTk.PhotoImage(image.copy())
            label.configure(image=preview, text="")
            label.image = preview
        except OSError:
            label.configure(image="", text="Vista previa no disponible")
            label.image = None

    def _preview_selection(self, box, paths, preview):
        selected = box.curselection()
        if selected:
            self._show_preview(paths[selected[-1]], preview)

    def mark_copies(self):
        if self.exact_tree.selection():
            self.exact_list.selection_clear(0, "end")
            if self.exact_list.size() > 1:
                self.exact_list.selection_set(1, "end")

    def move_group(self, exact):
        tree, box = (self.exact_tree, self.exact_list) if exact else (self.version_tree, self.version_list)
        selected = tree.selection()
        if selected:
            group = (self.groups if exact else self.versions)[int(selected[0])]
            paths = [group[i].path for i in box.curselection()]
            if not paths:
                messagebox.showinfo("Sin selección", "Marcá las fotos que querés mover.")
            elif messagebox.askyesno("Confirmar movimiento", f"¿Mover {len(paths)} foto(s) a FotosClaras_ParaRevisar? Podés deshacer el último movimiento."):
                try:
                    quarantine(paths, self.folder)
                    self._after_move(len(paths))
                except (OSError, ValueError) as error:
                    messagebox.showerror("No se pudieron mover", str(error))

    def analyze_faces(self):
        if self.photos:
            self._start(lambda progress: scan_faces(self.photos, progress), self._faces_done)

    def _faces_done(self, result):
        self.people, self.no_faces, self.face_counts, errors = result
        self.render_people(self.settings["last_person_id"])
        self.noface_list.delete(0, "end")
        for path in self.no_faces:
            self.noface_list.insert("end", str(Path(path).relative_to(self.folder)))
        self.filter_people.delete(0, "end")
        for person in self.people:
            self.filter_people.insert("end", person["name"] or f"Persona sin nombre ({person['id'][:5]})")
        self.update_filter()
        self.settings["faces_analyzed"] = True
        save_settings(self.settings)
        self.status.config(text=f"{len(self.people)} grupos de personas · {len(self.no_faces)} fotos sin rostro · {len(errors)} errores")
        self.tabs.select(self.settings["last_tab"] if self._resuming else 3)
        self._resuming = False
        if errors:
            messagebox.showwarning("Rostros", f"No se pudieron analizar {len(errors)} fotos. Ejemplo: {Path(errors[0][0]).name}: {errors[0][1]}")

    def render_people(self, selected_id=None):
        self.people_tree.delete(*self.people_tree.get_children())
        for i, person in enumerate(self.people):
            self.people_tree.insert("", "end", iid=str(i), text=person["name"] or f"Persona sin nombre {i+1}",
                                    values=(len(person["photos"]),))
        if self.people:
            index = next((i for i, p in enumerate(self.people) if p["id"] == selected_id), 0)
            self.people_tree.selection_set(str(index))
            self.show_person()

    def current_person(self):
        selection = self.people_tree.selection()
        return self.people[int(selection[0])] if selection else None

    def show_person(self, _=None):
        self.person_list.delete(0, "end")
        group = self.current_person()
        if group:
            self.settings["last_person_id"] = group["id"]
            save_settings(self.settings)
            for path in group["photos"]:
                self.person_list.insert("end", str(Path(path).relative_to(self.folder)))
            self._show_person_face(group, group["photos"][0])

    def show_person_photo(self, _=None):
        person, chosen = self.current_person(), self.person_list.curselection()
        if person and chosen:
            self._show_person_face(person, person["photos"][chosen[-1]])

    def _show_person_face(self, person, path):
        face = next((f for f in person["faces"] if f["path"] == path and Path(f["thumb"]).is_file()), None)
        self._show_preview(face["thumb"] if face else path, self.person_preview, enlarge=bool(face))
        self._show_preview(path, self.person_photo_preview)

    def _center_dialog(self, dialog, width, height):
        x = self.winfo_rootx() + max(0, (self.winfo_width() - width) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - height) // 2)
        dialog.geometry(f"{width}x{height}+{x}+{y}")

    def _ask_text(self, title, question, initial=""):
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.configure(bg=BG)
        self._center_dialog(dialog, 490, 230)
        dialog.resizable(False, False)
        dialog.transient(self)
        value = tk.StringVar(value=initial)
        result = [None]
        frame = ttk.Frame(dialog, padding=25)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=title, style="Section.TLabel").pack(anchor="w", pady=(0, 10))
        ttk.Label(frame, text=question, style="Muted.TLabel", wraplength=425).pack(anchor="w", pady=(0, 12))
        entry = ttk.Entry(frame, textvariable=value, font=("Segoe UI", 11))
        entry.pack(fill="x")
        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=(18, 0))
        def accept(_=None):
            result[0] = value.get()
            dialog.destroy()
        ttk.Button(actions, text="Cancelar", command=dialog.destroy).pack(side="right")
        ttk.Button(actions, text="Guardar", style="Accent.TButton", command=accept).pack(side="right", padx=(0, 9))
        entry.bind("<Return>", accept)
        dialog.bind("<Escape>", lambda event: dialog.destroy())
        dialog.grab_set()
        entry.focus_set()
        self.wait_window(dialog)
        return result[0]

    def _choose_person_to_merge(self, options):
        dialog = tk.Toplevel(self)
        dialog.title("Unir con otra persona")
        dialog.configure(bg=BG)
        self._center_dialog(dialog, 500, 530)
        dialog.transient(self)
        result = [None]
        visible = []
        frame = ttk.Frame(dialog, padding=22)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Unir con otra persona", style="Section.TLabel").pack(anchor="w")
        ttk.Label(frame, text="Buscá el nombre o elegí otro grupo de la lista.",
                  style="Muted.TLabel").pack(anchor="w", pady=(5, 12))
        term = tk.StringVar()
        entry = ttk.Entry(frame, textvariable=term, font=("Segoe UI", 11))
        entry.pack(fill="x", pady=(0, 12))
        body = ttk.Frame(frame)
        body.pack(fill="both", expand=True)
        listing = self._list(body, lambda event: None, multiple=False)
        def refresh(*_):
            visible[:] = [p for p in options if term.get().casefold() in
                          (p["name"] or "Persona sin nombre").casefold()]
            listing.delete(0, "end")
            for i, person in enumerate(visible):
                listing.insert("end", f"{person['name'] or 'Persona sin nombre'}  ·  {len(person['photos'])} fotos  ·  {person['id'][:6]}")
        def accept(_=None):
            selection = listing.curselection()
            if selection:
                result[0] = visible[selection[0]]
                dialog.destroy()
        term.trace_add("write", refresh)
        refresh()
        listing.bind("<Double-1>", accept)
        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=(15, 0))
        ttk.Button(actions, text="Cancelar", command=dialog.destroy).pack(side="right")
        ttk.Button(actions, text="Unir grupos", style="Accent.TButton", command=accept).pack(side="right", padx=(0, 9))
        dialog.bind("<Escape>", lambda event: dialog.destroy())
        dialog.grab_set()
        entry.focus_set()
        self.wait_window(dialog)
        return result[0]

    def name_person(self):
        person = self.current_person()
        if person:
            name = self._ask_text("Identificar persona", "¿Quién es esta persona? El nombre se aplica a todo este grupo.",
                                  initial=person["name"])
            if name is not None:
                try:
                    save_name(person, name)
                    self.people = regroup_after_naming(self.people)
                    self.render_people(person["id"])
                    self._refresh_person_filter()
                    self.status.config(text=f"{name.strip()}: {len(self.current_person()['photos'])} fotos agrupadas · revisá que todas correspondan")
                except (OSError, ValueError) as error:
                    messagebox.showerror("Nombre", str(error))

    def split_person(self):
        person = self.current_person()
        if person:
            selected = [person["photos"][i] for i in self.person_list.curselection()]
            try:
                new = split_group(person, selected)
                self.people.append(new)
                self.render_people(new["id"])
                self._refresh_person_filter()
            except (OSError, ValueError) as error:
                messagebox.showinfo("Separar fotos", str(error))

    def merge_person(self):
        source = self.current_person()
        if not source:
            return
        options = [p for p in self.people if p is not source]
        if not options:
            return
        target = self._choose_person_to_merge(options)
        if target:
            if messagebox.askyesno("Unir grupos", f"¿Unir los rostros seleccionados con {target['name'] or 'la otra persona'}?"):
                merge_groups(source, target)
                self.people.remove(source)
                self.render_people(target["id"])
                self._refresh_person_filter()

    def _refresh_person_filter(self):
        self.filter_people.delete(0, "end")
        for person in self.people:
            self.filter_people.insert("end", person["name"] or f"Persona sin nombre ({person['id'][:5]})")
        self.update_filter()

    def clear_person_filter(self):
        self.filter_people.selection_clear(0, "end")
        self.update_filter()

    def update_filter(self, _=None):
        choice = self.count_choice.get()
        if choice != self.settings["count_filter"]:
            self.settings["count_filter"] = choice
            save_settings(self.settings)
        selected = [set(self.people[i]["photos"]) for i in self.filter_people.curselection()]
        matching = []
        for photo in self.photos:
            count = self.face_counts.get(photo.path)
            if count is None:
                continue
            if choice == "0 rostros" and count != 0 or choice == "1 rostro" and count != 1 or choice == "2 rostros" and count != 2 or choice == "3 o más" and count < 3:
                continue
            if all(photo.path in paths for paths in selected):
                matching.append(photo.path)
        self.filtered_paths = matching
        self.filtered_list.delete(0, "end")
        for i in range(0, len(matching), 500):
            self.filtered_list.insert("end", *(str(Path(p).relative_to(self.folder)) for p in matching[i:i + 500]))
        self.filter_count.config(text=f"{len(matching)} fotos cumplen estos filtros")

    def move_person(self):
        person = self.current_person()
        if person:
            selected = [person["photos"][i] for i in self.person_list.curselection()]
            self.album_dialog(selected or person["photos"])

    def album_dialog(self, paths):
        if not paths:
            messagebox.showinfo("Sin selección", "Seleccioná al menos una foto.")
            return
        choice = messagebox.askyesnocancel("Destino de las fotos", "¿Querés crear un álbum nuevo?\n\nSí: crearlo dentro de Álbumes.\nNo: elegir una carpeta existente.\nCancelar: no mover.")
        if choice is None:
            return
        if choice:
            name = self._ask_text("Nuevo álbum", "Nombre del álbum nuevo:")
            if name is None:
                return
            name = name.strip()
            if not name or name in (".", "..") or any(char in name for char in '/\\<>:"|?*') or name.endswith((".", " ")):
                messagebox.showerror("Nombre inválido", "Usá un nombre de carpeta simple, sin barras ni caracteres especiales.")
                return
            destination = Path(self.folder) / "Álbumes" / name
            if destination.exists() and not destination.is_dir():
                messagebox.showerror("Álbum", "Ya existe un archivo con ese nombre.")
                return
        else:
            selected = filedialog.askdirectory(title="Elegí el álbum existente")
            if not selected:
                return
            destination = Path(selected)
        if not messagebox.askyesno("Confirmar movimiento", f"¿Mover {len(paths)} foto(s) a:\n{destination}\n\nSe conservan los archivos, se evita sobrescribir nombres y podés deshacer el último movimiento."):
            return
        try:
            moves = move_to_album(paths, self.folder, destination)
            self._after_move(len(moves))
        except (OSError, ValueError) as error:
            messagebox.showerror("No se pudieron mover", str(error))

    def _after_move(self, count):
        self.rescan_faces = bool(self.face_counts)
        self.analyze()
        self.status.config(text=f"Movidas {count} fotos. Podés deshacer el último movimiento.")

    def undo(self):
        if not self.folder or self.busy:
            return
        try:
            count = undo_last(self.folder)
        except (OSError, RuntimeError, ValueError) as error:
            messagebox.showerror("No se pudo deshacer", str(error))
            return
        if count:
            self._after_move(count)
        else:
            messagebox.showinfo("Deshacer", "No hay movimientos para deshacer.")


if __name__ == "__main__":
    FotosClaras().mainloop()
