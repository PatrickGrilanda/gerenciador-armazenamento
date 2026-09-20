from __future__ import annotations

import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

import customtkinter as ctk

from storage_manager import __version__
from storage_manager.config import APP_DISPLAY_NAME, GITHUB_REPO_FULL
from storage_manager.drives import DriveInfo, list_drives
from storage_manager.programs import InstalledProgram, list_installed_programs, run_uninstall
from storage_manager.scanner import EntrySize, LargeFile, find_large_files, format_bytes, scan_directory
from storage_manager.updater import ReleaseInfo, check_for_update, download_installer


class StorageManagerApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title(f"{APP_DISPLAY_NAME} v{__version__}")
        self.geometry("1100x700")
        self.minsize(900, 560)

        self._scan_thread: threading.Thread | None = None
        self._large_scan_thread: threading.Thread | None = None
        self._scan_cancel = threading.Event()
        self._large_scan_cancel = threading.Event()
        self._deep_folders_var = tk.BooleanVar(value=False)
        self._current_drive: DriveInfo | None = None
        self._current_path: str = ""
        self._programs: list[InstalledProgram] = []
        self._pending_release: ReleaseInfo | None = None
        self._update_busy = False

        self._build_ui()
        self.refresh_drives()
        self.after(800, self._check_updates_on_startup)

    def _build_ui(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        sidebar = ctk.CTkFrame(self, width=220, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_rowconfigure(2, weight=1)
        sidebar.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            sidebar,
            text="Volumes",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).grid(row=0, column=0, padx=16, pady=(16, 8), sticky="w")

        self.btn_refresh_drives = ctk.CTkButton(
            sidebar, text="Atualizar volumes", command=self.refresh_drives
        )
        self.btn_refresh_drives.grid(row=1, column=0, padx=16, pady=(0, 8), sticky="ew")

        self.drive_list = ctk.CTkScrollableFrame(sidebar, label_text="")
        self.drive_list.grid(row=2, column=0, padx=8, pady=8, sticky="nsew")

        update_box = ctk.CTkFrame(sidebar)
        update_box.grid(row=3, column=0, padx=12, pady=(0, 12), sticky="ew")
        ctk.CTkLabel(
            update_box,
            text=f"Versão {__version__}",
            font=ctk.CTkFont(size=12),
            text_color="gray",
        ).pack(anchor="w", padx=8, pady=(8, 4))
        self.btn_check_updates = ctk.CTkButton(
            update_box,
            text="Verificar atualizações",
            height=28,
            command=self.check_updates_manual,
        )
        self.btn_check_updates.pack(fill="x", padx=8, pady=(0, 8))

        main = ctk.CTkFrame(self, corner_radius=0)
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_rowconfigure(0, weight=1)
        main.grid_columnconfigure(0, weight=1)

        self._init_tree_styles()

        self.tabs = ctk.CTkTabview(main)
        self.tabs.grid(row=0, column=0, padx=12, pady=12, sticky="nsew")

        tab_large = self.tabs.add("Arquivos grandes")
        tab_explorer = self.tabs.add("Pastas e arquivos")
        tab_programs = self.tabs.add("Programas instalados")
        tab_updates = self.tabs.add("Atualizações")

        self._build_large_files_tab(tab_large)
        self._build_explorer_tab(tab_explorer)
        self._build_programs_tab(tab_programs)
        self._build_updates_tab(tab_updates)

    def _init_tree_styles(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Storage.Treeview",
            background="#2b2b2b",
            fieldbackground="#2b2b2b",
            foreground="#e0e0e0",
            rowheight=26,
        )
        style.configure(
            "Storage.Treeview.Heading",
            background="#1f538d",
            foreground="white",
            font=("Segoe UI", 10, "bold"),
        )

    def _build_explorer_tab(self, parent: ctk.CTkFrame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(2, weight=1)

        nav = ctk.CTkFrame(parent, fg_color="transparent")
        nav.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        nav.grid_columnconfigure(1, weight=1)

        self.btn_up = ctk.CTkButton(nav, text="Subir", width=80, command=self.go_up)
        self.btn_up.grid(row=0, column=0, padx=(0, 8))

        self.path_var = tk.StringVar(value="Selecione um volume à esquerda")
        self.path_entry = ctk.CTkEntry(nav, textvariable=self.path_var)
        self.path_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8))

        self.btn_scan = ctk.CTkButton(nav, text="Listar pasta", width=110, command=self.start_scan)
        self.btn_scan.grid(row=0, column=2, padx=(0, 8))

        self.btn_open_explorer = ctk.CTkButton(
            nav, text="Abrir no Explorer", width=140, command=self.open_in_explorer
        )
        self.btn_open_explorer.grid(row=0, column=3)

        options = ctk.CTkFrame(parent, fg_color="transparent")
        options.grid(row=4, column=0, sticky="ew", pady=(0, 4))
        ctk.CTkCheckBox(
            options,
            text="Calcular tamanho total de cada subpasta (lento)",
            variable=self._deep_folders_var,
        ).pack(anchor="w")

        self.scan_status = ctk.CTkLabel(parent, text="", anchor="w")
        self.scan_status.grid(row=1, column=0, sticky="ew", pady=(0, 4))

        tree_frame = ctk.CTkFrame(parent)
        tree_frame.grid(row=2, column=0, sticky="nsew")
        tree_frame.grid_columnconfigure(0, weight=1)
        tree_frame.grid_rowconfigure(0, weight=1)

        columns = ("size", "pct", "type")
        self.tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show="tree headings",
            style="Storage.Treeview",
            selectmode="browse",
        )
        self.tree.heading("#0", text="Nome", anchor="w")
        self.tree.heading("size", text="Tamanho", anchor="e")
        self.tree.heading("pct", text="% da pasta", anchor="e")
        self.tree.heading("type", text="Tipo", anchor="w")
        self.tree.column("#0", width=420, stretch=True)
        self.tree.column("size", width=100, stretch=False, anchor="e")
        self.tree.column("pct", width=90, stretch=False, anchor="e")
        self.tree.column("type", width=120, stretch=False)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        self.tree.bind("<Double-1>", self._on_tree_double_click)

        hint = ctk.CTkLabel(
            parent,
            text="Listagem rápida por nível. Para caçar espaço, use a aba Arquivos grandes.",
            text_color="gray",
            anchor="w",
        )
        hint.grid(row=3, column=0, sticky="ew", pady=(8, 0))

    def _build_large_files_tab(self, parent: ctk.CTkFrame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(2, weight=1)

        toolbar = ctk.CTkFrame(parent, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        toolbar.grid_columnconfigure(2, weight=1)

        ctk.CTkLabel(toolbar, text="Mínimo:").grid(row=0, column=0, padx=(0, 6))
        self.large_min_var = tk.StringVar(value="500 MB")
        self.large_min_menu = ctk.CTkOptionMenu(
            toolbar,
            variable=self.large_min_var,
            values=["100 MB", "250 MB", "500 MB", "1 GB", "2 GB", "5 GB"],
            width=110,
        )
        self.large_min_menu.grid(row=0, column=1, sticky="w", padx=(0, 12))

        self.large_path_var = tk.StringVar(value="Selecione um volume à esquerda")
        self.large_path_entry = ctk.CTkEntry(toolbar, textvariable=self.large_path_var)
        self.large_path_entry.grid(row=0, column=2, sticky="ew", padx=(0, 8))

        self.btn_large_scan = ctk.CTkButton(
            toolbar, text="Buscar", width=90, command=self.start_large_file_scan
        )
        self.btn_large_scan.grid(row=0, column=3, padx=(0, 8))

        self.btn_large_cancel = ctk.CTkButton(
            toolbar,
            text="Parar",
            width=80,
            fg_color="#5c5c5c",
            hover_color="#444444",
            command=self.cancel_large_file_scan,
        )
        self.btn_large_cancel.grid(row=0, column=4, padx=(0, 8))

        self.btn_large_select = ctk.CTkButton(
            toolbar,
            text="Mostrar no Explorer",
            width=150,
            command=self.reveal_large_file_in_explorer,
        )
        self.btn_large_select.grid(row=0, column=5)

        self.large_status = ctk.CTkLabel(parent, text="", anchor="w")
        self.large_status.grid(row=1, column=0, sticky="ew", pady=(0, 4))

        frame = ctk.CTkFrame(parent)
        frame.grid(row=2, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)

        cols = ("size", "modified", "folder")
        self.large_tree = ttk.Treeview(
            frame,
            columns=cols,
            show="tree headings",
            style="Storage.Treeview",
            selectmode="browse",
        )
        self.large_tree.heading("#0", text="Arquivo", anchor="w")
        self.large_tree.heading("size", text="Tamanho", anchor="e")
        self.large_tree.heading("modified", text="Modificado", anchor="w")
        self.large_tree.heading("folder", text="Pasta", anchor="w")
        self.large_tree.column("#0", width=280, stretch=True)
        self.large_tree.column("size", width=100, anchor="e")
        self.large_tree.column("modified", width=140)
        self.large_tree.column("folder", width=360, stretch=True)

        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.large_tree.yview)
        self.large_tree.configure(yscrollcommand=vsb.set)
        self.large_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        note = ctk.CTkLabel(
            parent,
            text="Busca paralela pelos maiores arquivos do volume (ignora links e junções). "
            "Pode levar alguns minutos em discos cheios, mas é o caminho mais direto para liberar espaço.",
            text_color="gray",
            anchor="w",
            wraplength=820,
            justify="left",
        )
        note.grid(row=3, column=0, sticky="ew", pady=(8, 0))

    def _build_programs_tab(self, parent: ctk.CTkFrame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(2, weight=1)

        toolbar = ctk.CTkFrame(parent, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        toolbar.grid_columnconfigure(1, weight=1)

        self.btn_load_programs = ctk.CTkButton(
            toolbar, text="Carregar programas", command=self.load_programs
        )
        self.btn_load_programs.grid(row=0, column=0, padx=(0, 8))

        self.program_search_var = tk.StringVar()
        self.program_search_var.trace_add("write", lambda *_: self._filter_programs())
        self.program_search = ctk.CTkEntry(
            toolbar, placeholder_text="Buscar por nome ou publicador…", textvariable=self.program_search_var
        )
        self.program_search.grid(row=0, column=1, sticky="ew", padx=(0, 8))

        self.btn_uninstall = ctk.CTkButton(
            toolbar,
            text="Desinstalar selecionado",
            fg_color="#b3261e",
            hover_color="#8c1d18",
            command=self.uninstall_selected,
        )
        self.btn_uninstall.grid(row=0, column=2)

        self.program_status = ctk.CTkLabel(parent, text="", anchor="w")
        self.program_status.grid(row=1, column=0, sticky="ew", pady=(0, 4))

        prog_frame = ctk.CTkFrame(parent)
        prog_frame.grid(row=2, column=0, sticky="nsew")
        prog_frame.grid_columnconfigure(0, weight=1)
        prog_frame.grid_rowconfigure(0, weight=1)

        prog_columns = ("publisher", "version", "size", "location")
        self.program_tree = ttk.Treeview(
            prog_frame,
            columns=prog_columns,
            show="tree headings",
            style="Storage.Treeview",
            selectmode="browse",
        )
        for col, title, width in (
            ("publisher", "Publicador", 160),
            ("version", "Versão", 90),
            ("size", "Tamanho (est.)", 110),
            ("location", "Pasta de instalação", 280),
        ):
            self.program_tree.heading(col, text=title)
            self.program_tree.column(col, width=width, stretch=(col == "location"))

        self.program_tree.heading("#0", text="Programa", anchor="w")
        self.program_tree.column("#0", width=260, stretch=True)

        prog_vsb = ttk.Scrollbar(prog_frame, orient="vertical", command=self.program_tree.yview)
        self.program_tree.configure(yscrollcommand=prog_vsb.set)
        self.program_tree.grid(row=0, column=0, sticky="nsew")
        prog_vsb.grid(row=0, column=1, sticky="ns")

        note = ctk.CTkLabel(
            parent,
            text="O tamanho vem do registro do Windows (quando disponível). A desinstalação abre o assistente oficial do programa.",
            text_color="gray",
            anchor="w",
            wraplength=800,
            justify="left",
        )
        note.grid(row=3, column=0, sticky="ew", pady=(8, 0))

    def _build_updates_tab(self, parent: ctk.CTkFrame) -> None:
        parent.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            parent,
            text="Atualizações automáticas via GitHub Releases",
            font=ctk.CTkFont(size=16, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 8))

        self.update_status = ctk.CTkLabel(
            parent,
            text=f"Você está na versão {__version__}.",
            anchor="w",
            justify="left",
        )
        self.update_status.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        self.update_notes = ctk.CTkTextbox(parent, height=220, wrap="word")
        self.update_notes.grid(row=2, column=0, sticky="nsew", pady=(0, 8))
        self.update_notes.configure(state="disabled")
        parent.grid_rowconfigure(2, weight=1)

        self.update_progress = ctk.CTkProgressBar(parent)
        self.update_progress.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        self.update_progress.set(0)

        actions = ctk.CTkFrame(parent, fg_color="transparent")
        actions.grid(row=4, column=0, sticky="ew")
        actions.grid_columnconfigure(0, weight=1)

        self.btn_install_update = ctk.CTkButton(
            actions,
            text="Baixar e instalar atualização",
            state="disabled",
            command=self.install_pending_update,
        )
        self.btn_install_update.grid(row=0, column=0, padx=(0, 8), sticky="w")

        ctk.CTkButton(
            actions,
            text="Abrir página de releases",
            command=lambda: webbrowser.open(f"https://github.com/{GITHUB_REPO_FULL}/releases"),
        ).grid(row=0, column=1, sticky="w")

        ctk.CTkButton(
            actions,
            text="Verificar agora",
            command=self.check_updates_manual,
        ).grid(row=0, column=2, padx=(8, 0), sticky="e")

    def _check_updates_on_startup(self) -> None:
        if self._update_busy:
            return
        self._update_busy = True
        self.update_status.configure(text="Verificando atualizações em segundo plano…")

        def worker() -> None:
            try:
                status, release = check_for_update()
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda: self._update_check_failed(str(exc), silent=True))
                return
            self.after(0, lambda: self._update_check_done(status, release, silent=True))

        threading.Thread(target=worker, daemon=True).start()

    def check_updates_manual(self) -> None:
        if self._update_busy:
            messagebox.showinfo("Atualizações", "Já existe uma verificação em andamento.")
            return
        self._update_busy = True
        self.btn_check_updates.configure(state="disabled")
        self.update_status.configure(text="Consultando GitHub Releases…")
        self.update_progress.set(0)

        def worker() -> None:
            try:
                status, release = check_for_update()
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda: self._update_check_failed(str(exc), silent=False))
                return
            self.after(0, lambda: self._update_check_done(status, release, silent=False))

        threading.Thread(target=worker, daemon=True).start()

    def _update_check_failed(self, message: str, *, silent: bool) -> None:
        self._update_busy = False
        self.btn_check_updates.configure(state="normal")
        self.update_status.configure(text=f"Não foi possível verificar atualizações: {message}")
        if not silent:
            messagebox.showerror("Atualizações", message)

    def _update_check_done(self, status: str, release: ReleaseInfo | None, *, silent: bool) -> None:
        self._update_busy = False
        self.btn_check_updates.configure(state="normal")
        self._pending_release = None
        self.btn_install_update.configure(state="disabled")
        self.update_notes.configure(state="normal")
        self.update_notes.delete("1.0", "end")

        if release is None:
            self.update_status.configure(text="Nenhuma release publicada ainda no GitHub.")
            self.update_notes.insert("end", "Quando a primeira versão for publicada, ela aparecerá aqui.")
            self.update_notes.configure(state="disabled")
            return

        notes = release.body.strip() or "(Sem notas de versão.)"
        self.update_notes.insert("end", notes)
        self.update_notes.configure(state="disabled")

        if status == "available":
            self._pending_release = release
            self.update_status.configure(
                text=f"Nova versão disponível: v{release.version} (você está na v{__version__})."
            )
            self.btn_install_update.configure(state="normal")
            if silent:
                if messagebox.askyesno(
                    "Atualização disponível",
                    f"A versão v{release.version} está disponível.\n\nDeseja abrir a aba Atualizações agora?",
                ):
                    self.tabs.set("Atualizações")
            else:
                messagebox.showinfo(
                    "Atualização disponível",
                    f"A versão v{release.version} pode ser instalada pelo botão na aba Atualizações.",
                )
            return

        self.update_status.configure(text=f"Você já está na versão mais recente (v{__version__}).")
        if not silent:
            messagebox.showinfo("Atualizações", "Nenhuma atualização encontrada. Você já está na versão mais recente.")

    def install_pending_update(self) -> None:
        release = self._pending_release
        if release is None:
            messagebox.showinfo("Atualizações", "Não há atualização pendente para instalar.")
            return
        if not messagebox.askyesno(
            "Instalar atualização",
            f"Baixar e instalar a versão v{release.version}?\n\n"
            "O aplicativo será fechado e o instalador será aberto. "
            "Siga os passos na tela para concluir.",
        ):
            return

        self._update_busy = True
        self.btn_install_update.configure(state="disabled")
        self.update_status.configure(text=f"Baixando {release.installer_name}…")
        self.update_progress.set(0)

        def worker() -> None:
            try:

                def on_progress(done: int, total: int) -> None:
                    if total > 0:
                        fraction = min(done / total, 1.0)
                        self.after(0, lambda: self.update_progress.set(fraction))

                installer_path = download_installer(release, on_progress=on_progress)
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda: self._update_install_failed(str(exc)))
                return
            self.after(0, lambda: self._launch_installer(installer_path))

        threading.Thread(target=worker, daemon=True).start()

    def _update_install_failed(self, message: str) -> None:
        self._update_busy = False
        self.btn_install_update.configure(state="normal" if self._pending_release else "disabled")
        self.update_status.configure(text=f"Falha ao baixar atualização: {message}")
        messagebox.showerror("Atualizações", message)

    def _launch_installer(self, installer_path) -> None:
        self.update_status.configure(text="Iniciando instalador…")
        try:
            subprocess.Popen(
                [str(installer_path), "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"],
                shell=False,
            )
        except Exception as exc:  # noqa: BLE001
            self._update_install_failed(str(exc))
            return
        self.destroy()

    def refresh_drives(self) -> None:
        for child in self.drive_list.winfo_children():
            child.destroy()

        drives = list_drives()
        if not drives:
            ctk.CTkLabel(self.drive_list, text="Nenhum volume encontrado.").pack(anchor="w", padx=8, pady=4)
            return

        for drive in drives:
            frame = ctk.CTkFrame(self.drive_list)
            frame.pack(fill="x", padx=4, pady=4)

            title = f"{drive.letter}:"
            if drive.label:
                title += f" {drive.label}"
            ctk.CTkLabel(frame, text=title, font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=8, pady=(6, 0))

            used_pct = (drive.used_bytes / drive.total_bytes * 100) if drive.total_bytes else 0
            ctk.CTkLabel(
                frame,
                text=f"{drive.drive_type} · {format_bytes(drive.used_bytes)} usados de {format_bytes(drive.total_bytes)} ({used_pct:.0f}%)",
                font=ctk.CTkFont(size=11),
                text_color="gray",
            ).pack(anchor="w", padx=8, pady=(0, 4))

            bar = ctk.CTkProgressBar(frame, height=8)
            bar.set(min(used_pct / 100, 1.0))
            bar.pack(fill="x", padx=8, pady=(0, 6))

            actions = ctk.CTkFrame(frame, fg_color="transparent")
            actions.pack(fill="x", padx=8, pady=(0, 8))
            ctk.CTkButton(
                actions,
                text="Arquivos grandes",
                height=28,
                command=lambda d=drive: self.select_drive_large(d),
            ).pack(fill="x", pady=(0, 4))
            ctk.CTkButton(
                actions,
                text="Explorar pastas",
                height=28,
                fg_color="#3a3a3a",
                hover_color="#2e2e2e",
                command=lambda d=drive: self.select_drive_explorer(d),
            ).pack(fill="x")

    def select_drive_large(self, drive: DriveInfo) -> None:
        self._current_drive = drive
        self._current_path = drive.mount_path
        self.path_var.set(self._current_path)
        self.large_path_var.set(self._current_path)
        self.tabs.set("Arquivos grandes")
        self.start_large_file_scan()

    def select_drive_explorer(self, drive: DriveInfo) -> None:
        self._current_drive = drive
        self._current_path = drive.mount_path
        self.path_var.set(self._current_path)
        self.large_path_var.set(self._current_path)
        self.tabs.set("Pastas e arquivos")
        self.start_scan()

    def go_up(self) -> None:
        if not self._current_path:
            return
        parent = self._current_path.rstrip("\\")
        if len(parent) <= 2 and parent.endswith(":"):
            return
        import os

        new_path = os.path.dirname(parent.rstrip("\\"))
        if not new_path.endswith("\\"):
            new_path += "\\"
        self._current_path = new_path
        self.path_var.set(self._current_path)
        self.start_scan()

    def start_scan(self) -> None:
        path = self.path_var.get().strip()
        if not path:
            messagebox.showwarning("Pasta", "Informe ou selecione uma pasta para analisar.")
            return
        if self._scan_thread and self._scan_thread.is_alive():
            messagebox.showinfo("Análise", "Já existe uma análise em andamento.")
            return

        self._current_path = path
        self._scan_cancel.clear()
        self.btn_scan.configure(state="disabled")
        self.scan_status.configure(text=f"Analisando {path}…")
        self._clear_tree(self.tree)

        deep = self._deep_folders_var.get()

        def worker() -> None:
            try:
                entries = scan_directory(
                    path,
                    deep_folders=deep,
                    cancel=self._scan_cancel,
                    on_progress=lambda p: self.after(
                        0, lambda: self.scan_status.configure(text=f"Calculando pasta: {p}…")
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda: self._scan_failed(str(exc)))
                return
            self.after(0, lambda: self._scan_done(entries))

        self._scan_thread = threading.Thread(target=worker, daemon=True)
        self._scan_thread.start()

    def _scan_failed(self, message: str) -> None:
        self.btn_scan.configure(state="normal")
        self.scan_status.configure(text="")
        messagebox.showerror("Erro na análise", message)

    def _scan_done(self, entries: list[EntrySize]) -> None:
        self.btn_scan.configure(state="normal")
        if self._scan_cancel.is_set():
            self.scan_status.configure(text="Listagem cancelada.")
            return
        known = [e for e in entries if not e.folder_size_unknown]
        total = sum(e.size_bytes for e in known)
        mode = "com tamanho de subpastas" if self._deep_folders_var.get() else "rápida"
        self.scan_status.configure(
            text=f"{len(entries)} itens ({mode}) · soma dos itens com tamanho conhecido: {format_bytes(total)}"
        )
        self._populate_tree(entries, total)

    def _clear_tree(self, tree: ttk.Treeview) -> None:
        for item in tree.get_children():
            tree.delete(item)

    def _populate_tree(self, entries: list[EntrySize], total: int) -> None:
        self._clear_tree(self.tree)
        for entry in entries:
            if entry.folder_size_unknown:
                size_text = "—"
                pct_text = "—"
            else:
                pct = (entry.size_bytes / total * 100) if total else 0
                size_text = format_bytes(entry.size_bytes)
                pct_text = f"{pct:.1f}%"
            kind = "Pasta" if entry.is_dir else "Arquivo"
            if entry.is_dir and entry.child_count:
                kind += f" ({entry.child_count} itens)"
            self.tree.insert(
                "",
                "end",
                text=entry.name,
                values=(size_text, pct_text, kind),
                tags=(entry.path, "dir" if entry.is_dir else "file"),
            )

    def _on_tree_double_click(self, _event: tk.Event) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        item = sel[0]
        tags = self.tree.item(item, "tags")
        if not tags:
            return
        path, kind = tags[0], tags[1] if len(tags) > 1 else ""
        if kind != "dir":
            return
        self._current_path = path if path.endswith("\\") else path + "\\"
        self.path_var.set(self._current_path)
        self.start_scan()

    def open_in_explorer(self) -> None:
        path = self.path_var.get().strip() or self._current_path
        if not path:
            return
        import subprocess

        subprocess.Popen(["explorer", path if path.endswith("\\") else path])

    def _parse_min_size_bytes(self) -> int:
        label = self.large_min_var.get().strip().upper()
        mapping = {
            "100 MB": 100 * 1024 * 1024,
            "250 MB": 250 * 1024 * 1024,
            "500 MB": 500 * 1024 * 1024,
            "1 GB": 1024 * 1024 * 1024,
            "2 GB": 2 * 1024 * 1024 * 1024,
            "5 GB": 5 * 1024 * 1024 * 1024,
        }
        return mapping.get(label, 500 * 1024 * 1024)

    def start_large_file_scan(self) -> None:
        path = self.large_path_var.get().strip()
        if not path:
            messagebox.showwarning("Busca", "Informe o volume ou pasta para buscar arquivos grandes.")
            return
        if self._large_scan_thread and self._large_scan_thread.is_alive():
            messagebox.showinfo("Busca", "Já existe uma busca em andamento.")
            return

        self._large_scan_cancel.clear()
        self.btn_large_scan.configure(state="disabled")
        self.large_status.configure(text=f"Buscando arquivos grandes em {path}…")
        self._clear_tree(self.large_tree)
        min_bytes = self._parse_min_size_bytes()

        def worker() -> None:
            try:

                def on_progress(count: int, current: str) -> None:
                    self.after(
                        0,
                        lambda: self.large_status.configure(
                            text=f"{count:,} arquivos verificados · {current}"
                        ),
                    )

                results = find_large_files(
                    path,
                    min_bytes=min_bytes,
                    cancel=self._large_scan_cancel,
                    on_progress=on_progress,
                )
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda: self._large_scan_failed(str(exc)))
                return
            self.after(0, lambda: self._large_scan_done(results, min_bytes))

        self._large_scan_thread = threading.Thread(target=worker, daemon=True)
        self._large_scan_thread.start()

    def cancel_large_file_scan(self) -> None:
        self._large_scan_cancel.set()
        self.large_status.configure(text="Parando busca…")

    def _large_scan_failed(self, message: str) -> None:
        self.btn_large_scan.configure(state="normal")
        self.large_status.configure(text="")
        messagebox.showerror("Busca", message)

    def _large_scan_done(self, results: list[LargeFile], min_bytes: int) -> None:
        self.btn_large_scan.configure(state="normal")
        if self._large_scan_cancel.is_set():
            self.large_status.configure(text="Busca interrompida.")
            return
        self._clear_tree(self.large_tree)
        for item in results:
            import os

            folder = os.path.dirname(item.path)
            modified = item.modified_at.strftime("%d/%m/%Y %H:%M") if item.modified_at else "—"
            self.large_tree.insert(
                "",
                "end",
                text=item.name,
                values=(format_bytes(item.size_bytes), modified, folder),
                tags=(item.path,),
            )
        total_size = sum(r.size_bytes for r in results)
        self.large_status.configure(
            text=f"{len(results)} maiores arquivos ≥ {format_bytes(min_bytes)} · "
            f"soma listada: {format_bytes(total_size)}"
        )

    def reveal_large_file_in_explorer(self) -> None:
        sel = self.large_tree.selection()
        if not sel:
            messagebox.showinfo("Explorer", "Selecione um arquivo na lista.")
            return
        tags = self.large_tree.item(sel[0], "tags")
        if not tags:
            return
        import os

        path = os.path.normpath(tags[0])
        subprocess.Popen(["explorer", "/select,", path])

    def load_programs(self) -> None:
        self.btn_load_programs.configure(state="disabled")
        self.program_status.configure(text="Lendo programas instalados…")
        self._clear_tree(self.program_tree)

        def worker() -> None:
            try:
                programs = list_installed_programs()
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda: self._programs_failed(str(exc)))
                return
            self.after(0, lambda: self._programs_loaded(programs))

        threading.Thread(target=worker, daemon=True).start()

    def _programs_failed(self, message: str) -> None:
        self.btn_load_programs.configure(state="normal")
        self.program_status.configure(text="")
        messagebox.showerror("Programas", message)

    def _programs_loaded(self, programs: list[InstalledProgram]) -> None:
        self._programs = programs
        self.btn_load_programs.configure(state="normal")
        self.program_status.configure(text=f"{len(programs)} programas com desinstalador registrado.")
        self._filter_programs()

    def _filter_programs(self) -> None:
        query = self.program_search_var.get().strip().lower()
        self._clear_tree(self.program_tree)
        for program in self._programs:
            haystack = f"{program.name} {program.publisher}".lower()
            if query and query not in haystack:
                continue
            size = format_bytes(program.estimated_size_bytes) if program.estimated_size_kb else "—"
            self.program_tree.insert(
                "",
                "end",
                text=program.name,
                values=(program.publisher, program.version, size, program.install_location),
                tags=(program.name,),
            )

    def uninstall_selected(self) -> None:
        sel = self.program_tree.selection()
        if not sel:
            messagebox.showinfo("Desinstalar", "Selecione um programa na lista.")
            return
        name = self.program_tree.item(sel[0], "text")
        program = next((p for p in self._programs if p.name == name), None)
        if program is None:
            messagebox.showerror("Desinstalar", "Programa não encontrado.")
            return

        if not messagebox.askyesno(
            "Confirmar desinstalação",
            f"Desinstalar “{program.name}”?\n\nSerá aberto o desinstalador oficial do Windows/programa.",
        ):
            return

        try:
            run_uninstall(program)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Desinstalar", str(exc))
            return

        messagebox.showinfo(
            "Desinstalação",
            "O assistente de desinstalação foi iniciado. Conclua os passos na janela que abriu.",
        )


def main() -> None:
    if sys.platform != "win32":
        print("Este aplicativo foi feito para Windows. Execute no PowerShell ou CMD do Windows.")
        sys.exit(1)
    app = StorageManagerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
