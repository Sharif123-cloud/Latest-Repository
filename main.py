import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog, scrolledtext
import os, sys, json, shutil, io, re, time, base64
from pathlib import Path
from datetime import datetime, timedelta
import sqlite3
import threading

try:
    import fitz  # PyMuPDF
except ImportError:
    messagebox.showerror("Missing Library", "Please install PyMuPDF: pip install PyMuPDF")
    sys.exit(1)

from PIL import Image, ImageTk
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet
from ebooklib import epub
from bs4 import BeautifulSoup

# ------------------------------
# Constants
# ------------------------------
APP_NAME = "BOOKS Reader"
APP_DATA_DIR = Path.home() / "BooksReaderData"
APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = APP_DATA_DIR / "books.db"
CONFIG_PATH = APP_DATA_DIR / "config.enc"
KEY_PATH = APP_DATA_DIR / ".keyfile"
REQUIRED_PASSWORD = "SSERUNJOGISHARIF47@GMAIL.COM"
REAUTH_DAYS = 2

# Color palette
CREAM = "#FDFBF7"
DEEP_TEAL = "#2A9D8F"
AMBER = "#E9C46A"
DARK_BG = "#1E272E"
LIGHT_TEXT = "#2E3B32"
DARK_TEXT = "#ECF0F1"

# ------------------------------
# Security & config helpers
# ------------------------------
def get_fernet():
    if not KEY_PATH.exists():
        key = Fernet.generate_key()
        with open(KEY_PATH, "wb") as f:
            f.write(key)
    else:
        key = open(KEY_PATH, "rb").read()
    return Fernet(key)

def encrypt_config(data: dict):
    f = get_fernet()
    return f.encrypt(json.dumps(data).encode())

def decrypt_config(encrypted: bytes):
    f = get_fernet()
    return json.loads(f.decrypt(encrypted))

def load_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "rb") as f:
            encrypted = f.read()
        return decrypt_config(encrypted)
    return {}

def save_config(data: dict):
    encrypted = encrypt_config(data)
    with open(CONFIG_PATH, "wb") as f:
        f.write(encrypted)

# ------------------------------
# Database setup
# ------------------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_type TEXT NOT NULL,
            added_date TEXT DEFAULT (datetime('now')),
            last_opened TEXT,
            last_page INTEGER DEFAULT 0,
            total_pages INTEGER DEFAULT 0,
            file_size INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS bookmarks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL,
            page INTEGER NOT NULL,
            note TEXT,
            created TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS highlights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL,
            page INTEGER,
            text TEXT,
            position TEXT,
            created TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL,
            page INTEGER,
            content TEXT,
            created TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS reading_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL,
            start_time TEXT,
            end_time TEXT,
            pages_read INTEGER DEFAULT 0,
            FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE
        );
    """)
    conn.commit()
    conn.close()

# ------------------------------
# Main Application class
# ------------------------------
class BooksApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("1200x750")
        self.root.configure(bg=CREAM)

        self.current_book = None
        self.current_page = 1
        self.zoom = 1.0
        self.font_size = 12
        self.theme = "light"
        self.pdf_doc = None
        self.epub_book = None
        self.epub_chapters = []
        self.current_chapter_idx = 0
        self.search_results = []
        self.result_index = -1
        self.focus_mode = False
        self.reading_session_start = None
        self.pages_read_this_session = 0

        if not self.authenticate():
            sys.exit(0)

        self.build_ui()
        self.load_library()
        self.apply_theme()

    def authenticate(self):
        config = load_config()
        ph = PasswordHasher()
        if "password_hash" not in config:
            config["password_hash"] = ph.hash(REQUIRED_PASSWORD)
            config["last_auth"] = datetime.now().isoformat()
            save_config(config)
            return True
        else:
            last_auth = datetime.fromisoformat(config.get("last_auth", "2000-01-01"))
            if (datetime.now() - last_auth).days >= REAUTH_DAYS:
                pwd = self.password_dialog()
                if pwd is None:
                    return False
                try:
                    ph.verify(config["password_hash"], pwd)
                    config["last_auth"] = datetime.now().isoformat()
                    save_config(config)
                    return True
                except VerifyMismatchError:
                    messagebox.showerror("Access Denied", "Incorrect password.")
                    return False
            else:
                return True

    def password_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Re-authentication Required")
        dlg.geometry("350x150")
        dlg.configure(bg=DEEP_TEAL)
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.resizable(False, False)

        tk.Label(dlg, text="Enter master password:", bg=DEEP_TEAL, fg="white",
                 font=("Arial", 11)).pack(pady=10)
        pwd_var = tk.StringVar()
        entry = tk.Entry(dlg, textvariable=pwd_var, show="*", font=("Arial", 11))
        entry.pack(pady=5)
        entry.focus()

        result = {"pwd": None}

        def submit():
            result["pwd"] = pwd_var.get()
            dlg.destroy()

        entry.bind("<Return>", lambda e: submit())
        tk.Button(dlg, text="Unlock", command=submit, bg=AMBER, fg="black").pack(pady=5)
        self.root.wait_window(dlg)
        return result["pwd"]

    def build_ui(self):
        self.main_paned = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, bg=CREAM)
        self.main_paned.pack(fill=tk.BOTH, expand=True)

        self.sidebar = tk.Frame(self.main_paned, bg=DEEP_TEAL, width=250)
        self.main_paned.add(self.sidebar, minsize=200)

        tk.Label(self.sidebar, text="📚 Library", font=("Arial", 14, "bold"),
                 bg=DEEP_TEAL, fg="white").pack(pady=10)
        self.import_btn = tk.Button(self.sidebar, text="Import Books", command=self.import_books,
                                    bg=AMBER, fg="black", font=("Arial", 10, "bold"))
        self.import_btn.pack(pady=5, padx=10, fill=tk.X)
        self.book_listbox = tk.Listbox(self.sidebar, bg="white", fg=LIGHT_TEXT,
                                       font=("Arial", 10), selectbackground=AMBER)
        self.book_listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        self.book_listbox.bind("<Double-Button-1>", lambda e: self.open_selected_book())
        self.book_listbox.bind("<<ListboxSelect>>", self.on_book_select)

        self.stats_btn = tk.Button(self.sidebar, text="Reading Stats", command=self.show_stats,
                                   bg="#E76F51", fg="white")
        self.stats_btn.pack(pady=5, padx=10, fill=tk.X)

        self.reader_frame = tk.Frame(self.main_paned, bg=CREAM)
        self.main_paned.add(self.reader_frame, stretch="always")

        self.toolbar = tk.Frame(self.reader_frame, bg=CREAM, relief=tk.RAISED, bd=1)
        self.toolbar.pack(side=tk.TOP, fill=tk.X)

        self.back_btn = tk.Button(self.toolbar, text="← Library", command=self.back_to_library,
                                  bg=DEEP_TEAL, fg="white")
        self.back_btn.pack(side=tk.LEFT, padx=5, pady=5)
        self.prev_btn = tk.Button(self.toolbar, text="◀", command=self.prev_page, bg=DEEP_TEAL, fg="white")
        self.prev_btn.pack(side=tk.LEFT, padx=2)
        self.page_label = tk.Label(self.toolbar, text="Page: 1", bg=CREAM, fg=LIGHT_TEXT,
                                   font=("Arial", 10, "bold"))
        self.page_label.pack(side=tk.LEFT, padx=5)
        self.next_btn = tk.Button(self.toolbar, text="▶", command=self.next_page, bg=DEEP_TEAL, fg="white")
        self.next_btn.pack(side=tk.LEFT, padx=2)

        self.font_smaller_btn = tk.Button(self.toolbar, text="A-", command=self.font_smaller,
                                          bg=DEEP_TEAL, fg="white")
        self.font_smaller_btn.pack(side=tk.LEFT, padx=2)
        self.font_larger_btn = tk.Button(self.toolbar, text="A+", command=self.font_larger,
                                         bg=DEEP_TEAL, fg="white")
        self.font_larger_btn.pack(side=tk.LEFT, padx=2)

        self.theme_btn = tk.Button(self.toolbar, text="🌓 Theme", command=self.toggle_theme,
                                   bg=DEEP_TEAL, fg="white")
        self.theme_btn.pack(side=tk.LEFT, padx=5)

        self.search_var = tk.StringVar()
        self.search_entry = tk.Entry(self.toolbar, textvariable=self.search_var, width=20,
                                     font=("Arial", 10))
        self.search_entry.pack(side=tk.LEFT, padx=5)
        self.search_btn = tk.Button(self.toolbar, text="Find", command=self.do_search,
                                    bg=AMBER, fg="black")
        self.search_btn.pack(side=tk.LEFT, padx=2)
        self.search_next_btn = tk.Button(self.toolbar, text="Next", command=self.search_next,
                                         bg=AMBER, fg="black")
        self.search_next_btn.pack(side=tk.LEFT, padx=2)

        self.bookmark_btn = tk.Button(self.toolbar, text="🔖 Bookmark", command=self.add_bookmark,
                                      bg=DEEP_TEAL, fg="white")
        self.bookmark_btn.pack(side=tk.LEFT, padx=5)
        self.highlight_btn = tk.Button(self.toolbar, text="🖍 Highlight", command=self.add_highlight,
                                       bg=DEEP_TEAL, fg="white")
        self.highlight_btn.pack(side=tk.LEFT, padx=5)
        self.note_btn = tk.Button(self.toolbar, text="📝 Note", command=self.add_note,
                                  bg=DEEP_TEAL, fg="white")
        self.note_btn.pack(side=tk.LEFT, padx=5)
        self.focus_btn = tk.Button(self.toolbar, text="Focus", command=self.toggle_focus,
                                   bg=AMBER, fg="black")
        self.focus_btn.pack(side=tk.LEFT, padx=5)

        self.content_frame = tk.Frame(self.reader_frame, bg=CREAM)
        self.content_frame.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(self.content_frame, bg=CREAM, highlightthickness=0)
        self.canvas.pack_forget()
        self.v_scroll = tk.Scrollbar(self.content_frame, orient=tk.VERTICAL)
        self.v_scroll.pack_forget()
        self.h_scroll = tk.Scrollbar(self.content_frame, orient=tk.HORIZONTAL)
        self.h_scroll.pack_forget()

        self.epub_text = tk.Text(self.content_frame, wrap=tk.WORD, bg=CREAM,
                                 fg=LIGHT_TEXT, font=("Arial", 12), padx=20, pady=20,
                                 state=tk.DISABLED)
        self.epub_scroll = tk.Scrollbar(self.content_frame, command=self.epub_text.yview)
        self.epub_text.configure(yscrollcommand=self.epub_scroll.set)
        self.epub_text.pack_forget()
        self.epub_scroll.pack_forget()

        self.side_panel = tk.Frame(self.reader_frame, bg=DEEP_TEAL, width=250)
        self.side_panel.pack_forget()
        tk.Label(self.side_panel, text="Bookmarks & Notes", bg=DEEP_TEAL, fg="white",
                 font=("Arial", 12, "bold")).pack(pady=10)
        self.notes_listbox = tk.Listbox(self.side_panel, bg="white")
        self.notes_listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.status = tk.Label(self.root, text="Ready", bg=CREAM, fg=LIGHT_TEXT, anchor=tk.W)
        self.status.pack(side=tk.BOTTOM, fill=tk.X)

    def load_library(self):
        self.book_listbox.delete(0, tk.END)
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id, title FROM books ORDER BY title")
        for row in c.fetchall():
            self.book_listbox.insert(tk.END, f"  {row[1]}  ")
            self.book_listbox.itemconfig(tk.END, {'bg': 'white'})
        conn.close()

    def import_books(self):
        files = filedialog.askopenfilenames(
            title="Select Books (PDF/EPUB)",
            filetypes=[("Books", "*.pdf *.epub"), ("All Files", "*.*")]
        )
        if not files:
            return
        imported = 0
        for file_path in files:
            file_path = Path(file_path)
            if file_path.suffix.lower() not in ['.pdf', '.epub']:
                continue
            dest = APP_DATA_DIR / file_path.name
            if dest.exists():
                dest = APP_DATA_DIR / f"{file_path.stem}_{int(time.time())}{file_path.suffix}"
            shutil.copy2(file_path, dest)
            file_type = 'pdf' if file_path.suffix.lower() == '.pdf' else 'epub'
            total_pages = 0
            if file_type == 'pdf':
                try:
                    doc = fitz.open(dest)
                    total_pages = len(doc)
                    doc.close()
                except:
                    total_pages = 0
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("INSERT INTO books (title, file_path, file_type, file_size, total_pages) VALUES (?, ?, ?, ?, ?)",
                      (file_path.stem, str(dest), file_type, os.path.getsize(dest), total_pages))
            conn.commit()
            conn.close()
            imported += 1
        if imported:
            messagebox.showinfo("Import Complete", f"Imported {imported} book(s).")
            self.load_library()
        else:
            messagebox.showwarning("No Books", "No valid PDF/EPUB files selected.")

    def on_book_select(self, event):
        selection = self.book_listbox.curselection()
        if selection:
            title = self.book_listbox.get(selection[0]).strip()
            self.status.config(text=f"Selected: {title}")

    def open_selected_book(self):
        selection = self.book_listbox.curselection()
        if not selection:
            return
        title = self.book_listbox.get(selection[0]).strip()
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id, file_path, file_type, last_page FROM books WHERE title=?", (title,))
        book = c.fetchone()
        conn.close()
        if not book:
            messagebox.showerror("Error", "Book not found in database.")
            return
        book_id, file_path, file_type, last_page = book
        self.open_book(book_id, file_path, file_type, last_page)

    def open_book(self, book_id, file_path, file_type, last_page=0):
        self.save_reading_session()
        self.current_book = book_id
        self.current_page = max(1, last_page)
        self.search_results.clear()
        self.result_index = -1
        self.reading_session_start = datetime.now()
        self.pages_read_this_session = 0

        if file_type == 'pdf':
            self.show_pdf(file_path)
        elif file_type == 'epub':
            self.show_epub(file_path)
        else:
            return

        conn = sqlite3.connect(DB_PATH)
        conn.execute("UPDATE books SET last_opened = ? WHERE id = ?",
                     (datetime.now().isoformat(), book_id))
        conn.commit()
        conn.close()

        self.status.config(text=f"Reading: {Path(file_path).name}")

    def save_reading_session(self):
        if self.current_book and self.reading_session_start:
            conn = sqlite3.connect(DB_PATH)
            now = datetime.now().isoformat()
            conn.execute("INSERT INTO reading_sessions (book_id, start_time, end_time, pages_read) VALUES (?, ?, ?, ?)",
                         (self.current_book, self.reading_session_start.isoformat(), now, self.pages_read_this_session))
            conn.execute("UPDATE books SET last_page = ? WHERE id = ?",
                         (self.current_page, self.current_book))
            conn.commit()
            conn.close()

    def back_to_library(self):
        self.save_reading_session()
        self.current_book = None
        self.clear_reader()
        self.status.config(text="Ready")

    def clear_reader(self):
        self.canvas.pack_forget()
        self.v_scroll.pack_forget()
        self.h_scroll.pack_forget()
        self.epub_text.pack_forget()
        self.epub_scroll.pack_forget()
        self.side_panel.pack_forget()
        self.page_label.config(text="Page: -")
        self.pdf_doc = None
        self.epub_book = None
        self.epub_chapters = []

    def show_pdf(self, file_path):
        self.clear_reader()
        try:
            self.pdf_doc = fitz.open(file_path)
        except Exception as e:
            messagebox.showerror("PDF Error", str(e))
            return
        self.epub_text.pack_forget()
        self.epub_scroll.pack_forget()
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.configure(yscrollcommand=self.v_scroll.set, xscrollcommand=self.h_scroll.set)
        self.v_scroll.config(command=self.canvas.yview)
        self.h_scroll.config(command=self.canvas.xview)
        self.canvas.bind("<Configure>", lambda e: self.render_pdf_page())
        self.canvas.bind("<MouseWheel>", self.on_mousewheel)
        self.render_pdf_page()

    def render_pdf_page(self):
        if not self.pdf_doc:
            return
        page = self.pdf_doc[self.current_page - 1]
        mat = fitz.Matrix(self.zoom, self.zoom)
        pix = page.get_pixmap(matrix=mat)
        img_data = pix.tobytes("ppm")
        img = Image.open(io.BytesIO(img_data))
        self.pdf_image = ImageTk.PhotoImage(img)
        self.canvas.delete("all")
        self.canvas.config(scrollregion=(0, 0, img.width, img.height))
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.pdf_image)
        self.page_label.config(text=f"Page: {self.current_page} / {len(self.pdf_doc)}")
        self.draw_search_highlights()

    def draw_search_highlights(self):
        if not self.search_results:
            return
        for (pg, quad) in self.search_results:
            if pg == self.current_page - 1:
                x0, y0, x1, y1 = quad.rect
                self.canvas.create_rectangle(x0 * self.zoom, y0 * self.zoom,
                                             x1 * self.zoom, y1 * self.zoom,
                                             outline=AMBER, width=2, tags="highlight")

    def on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def font_smaller(self):
        if self.pdf_doc:
            self.zoom = max(0.5, self.zoom - 0.1)
            self.render_pdf_page()
        else:
            self.font_size = max(8, self.font_size - 1)
            self.update_epub_font()

    def font_larger(self):
        if self.pdf_doc:
            self.zoom = min(3.0, self.zoom + 0.1)
            self.render_pdf_page()
        else:
            self.font_size = min(24, self.font_size + 1)
            self.update_epub_font()

    def show_epub(self, file_path):
        self.clear_reader()
        try:
            self.epub_book = epub.read_epub(file_path)
        except Exception as e:
            messagebox.showerror("EPUB Error", str(e))
            return
        self.epub_chapters = []
        for item in self.epub_book.get_items_of_type(9):
            soup = BeautifulSoup(item.get_content(), "html.parser")
            text = soup.get_text(separator="\n")
            if text.strip():
                self.epub_chapters.append(text.strip())
        if not self.epub_chapters:
            self.epub_chapters.append("(No text content found)")
        self.canvas.pack_forget()
        self.v_scroll.pack_forget()
        self.h_scroll.pack_forget()
        self.epub_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.epub_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.epub_text.configure(state=tk.NORMAL)
        self.epub_text.delete("1.0", tk.END)
        self.current_chapter_idx = self.current_page - 1
        if self.current_chapter_idx >= len(self.epub_chapters):
            self.current_chapter_idx = 0
            self.current_page = 1
        self.epub_text.insert(tk.END, self.epub_chapters[self.current_chapter_idx])
        self.epub_text.configure(state=tk.DISABLED)
        self.page_label.config(text=f"Page: {self.current_page} / {len(self.epub_chapters)}")
        self.update_epub_font()
        self.epub_text.yview_moveto(0)

    def update_epub_font(self):
        self.epub_text.configure(font=("Arial", self.font_size))

    def epub_prev_page(self):
        if self.current_chapter_idx > 0:
            self.current_chapter_idx -= 1
            self.current_page = self.current_chapter_idx + 1
            self.display_epub_chapter()

    def epub_next_page(self):
        if self.current_chapter_idx < len(self.epub_chapters) - 1:
            self.current_chapter_idx += 1
            self.current_page = self.current_chapter_idx + 1
            self.display_epub_chapter()

    def display_epub_chapter(self):
        self.epub_text.configure(state=tk.NORMAL)
        self.epub_text.delete("1.0", tk.END)
        self.epub_text.insert(tk.END, self.epub_chapters[self.current_chapter_idx])
        self.epub_text.configure(state=tk.DISABLED)
        self.page_label.config(text=f"Page: {self.current_page} / {len(self.epub_chapters)}")

    def prev_page(self):
        if self.pdf_doc:
            if self.current_page > 1:
                self.current_page -= 1
                self.render_pdf_page()
        elif self.epub_chapters:
            self.epub_prev_page()

    def next_page(self):
        if self.pdf_doc:
            if self.current_page < len(self.pdf_doc):
                self.current_page += 1
                self.render_pdf_page()
        elif self.epub_chapters:
            self.epub_next_page()

    def do_search(self):
        query = self.search_var.get().strip()
        if not query:
            return
        self.search_results.clear()
        self.result_index = -1
        if self.pdf_doc:
            for i in range(len(self.pdf_doc)):
                page = self.pdf_doc[i]
                areas = page.search_for(query)
                for a in areas:
                    self.search_results.append((i, a))
            if self.search_results:
                self.result_index = 0
                self.current_page = self.search_results[0][0] + 1
                self.render_pdf_page()
                messagebox.showinfo("Search", f"Found {len(self.search_results)} results.")
            else:
                messagebox.showinfo("Search", "No matches found.")
        elif self.epub_text:
            self.epub_text.tag_remove("search", "1.0", tk.END)
            start = "1.0"
            while True:
                pos = self.epub_text.search(query, start, stopindex=tk.END, nocase=True)
                if not pos:
                    break
                end = f"{pos}+{len(query)}c"
                self.epub_text.tag_add("search", pos, end)
                start = end
            self.epub_text.tag_config("search", background=AMBER)
            count = len(self.epub_text.tag_ranges("search"))
            if count:
                messagebox.showinfo("Search", f"Found {count//2} matches.")
            else:
                messagebox.showinfo("Search", "No matches.")
        else:
            messagebox.showinfo("Search", "No book open.")

    def search_next(self):
        if self.pdf_doc and self.search_results:
            if self.result_index < len(self.search_results) - 1:
                self.result_index += 1
                self.current_page = self.search_results[self.result_index][0] + 1
                self.render_pdf_page()
            else:
                messagebox.showinfo("Search", "No more results.")
        elif self.epub_text:
            messagebox.showinfo("Search", "Use 'Find' again to re-highlight.")

    def add_bookmark(self):
        if not self.current_book:
            return
        conn = sqlite3.connect(DB_PATH)
        conn.execute("INSERT INTO bookmarks (book_id, page) VALUES (?, ?)",
                     (self.current_book, self.current_page))
        conn.commit()
        conn.close()
        self.status.config(text="Bookmark added.")

    def add_highlight(self):
        if not self.current_book:
            return
        conn = sqlite3.connect(DB_PATH)
        conn.execute("INSERT INTO highlights (book_id, page, text) VALUES (?, ?, ?)",
                     (self.current_book, self.current_page, f"Highlight on page {self.current_page}"))
        conn.commit()
        conn.close()
        self.status.config(text="Highlight saved.")

    def add_note(self):
        if not self.current_book:
            return
        note = simpledialog.askstring("Add Note", "Enter your note:")
        if note:
            conn = sqlite3.connect(DB_PATH)
            conn.execute("INSERT INTO notes (book_id, page, content) VALUES (?, ?, ?)",
                         (self.current_book, self.current_page, note))
            conn.commit()
            conn.close()
            self.status.config(text="Note saved.")

    def toggle_focus(self):
        self.focus_mode = not self.focus_mode
        if self.focus_mode:
            self.main_paned.forget(self.sidebar)
            self.sidebar.pack_forget()
        else:
            self.main_paned.add(self.sidebar, before=self.reader_frame, minsize=200)
        self.focus_btn.config(text="Exit Focus" if self.focus_mode else "Focus")

    def toggle_theme(self):
        self.theme = "dark" if self.theme == "light" else "light"
        self.apply_theme()

    def apply_theme(self):
        bg = CREAM if self.theme == "light" else DARK_BG
        fg = LIGHT_TEXT if self.theme == "light" else DARK_TEXT
        self.root.configure(bg=bg)
        self.reader_frame.configure(bg=bg)
        self.toolbar.configure(bg=bg)
        self.page_label.configure(bg=bg, fg=fg)
        self.status.configure(bg=bg, fg=fg)
        self.canvas.configure(bg=bg)
        self.epub_text.configure(bg=bg, fg=fg, insertbackground=fg)

    def show_stats(self):
        if not self.current_book:
            messagebox.showinfo("Stats", "Open a book first.")
            return
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT SUM(pages_read), COUNT(*) FROM reading_sessions WHERE book_id=?",
                  (self.current_book,))
        total_pages, sessions = c.fetchone()
        conn.close()
        messagebox.showinfo("Reading Stats",
                            f"Total pages read: {total_pages or 0}\nSessions: {sessions or 0}")

    def on_close(self):
        self.save_reading_session()
        self.root.destroy()

if __name__ == "__main__":
    init_db()
    root = tk.Tk()
    app = BooksApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
