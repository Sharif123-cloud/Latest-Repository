import tkinter as tk
from tkinter import filedialog, messagebox, ttk, simpledialog
import json
import os
import shutil
import webbrowser
from pathlib import Path
from datetime import datetime, timedelta
import fitz  # PyMuPDF
from PIL import Image, ImageTk
import io

# ------------------------------
# Configuration
# ------------------------------
APP_DIR = Path.home() / "StudentReader"
APP_DIR.mkdir(exist_ok=True)
CONFIG_FILE = APP_DIR / "config.json"
LIBRARY_FILE = APP_DIR / "library.json"
BOOKMARKS_FILE = APP_DIR / "bookmarks.json"
NOTES_FILE = APP_DIR / "notes.json"
HIGHLIGHTS_FILE = APP_DIR / "highlights.json"
STATS_FILE = APP_DIR / "stats.json"
PASSWORD = "SSERUNJOGISHARIF47@GMAIL.COM"  # case-sensitive

# ------------------------------
# Security functions (2‑day re‑authentication)
# ------------------------------
def get_last_unlock():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, 'r') as f:
            data = json.load(f)
            return data.get("last_unlock", None)
    return None

def set_last_unlock():
    with open(CONFIG_FILE, 'w') as f:
        json.dump({"last_unlock": datetime.now().isoformat()}, f)

def needs_authentication():
    last = get_last_unlock()
    if last is None:
        return True
    last_time = datetime.fromisoformat(last)
    return datetime.now() - last_time > timedelta(days=2)

# ------------------------------
# Password dialog
# ------------------------------
def show_password_dialog():
    dialog = tk.Toplevel()
    dialog.title("Authentication")
    dialog.geometry("400x150")
    dialog.resizable(False, False)
    dialog.configure(bg="#F9F6F0")
    
    tk.Label(dialog, text="Enter master password:", bg="#F9F6F0", fg="#1A4A4A", font=("Inter", 12)).pack(pady=10)
    entry = tk.Entry(dialog, show="*", width=30, font=("Inter", 12))
    entry.pack(pady=5)
    error_label = tk.Label(dialog, text="", fg="red", bg="#F9F6F0")
    error_label.pack()
    
    def verify():
        if entry.get() == PASSWORD:
            set_last_unlock()
            dialog.destroy()
        else:
            error_label.config(text="Incorrect password. Case-sensitive.")
    
    tk.Button(dialog, text="Unlock", command=verify, bg="#E6A157", fg="#1A4A4A", font=("Inter", 10, "bold")).pack(pady=10)
    dialog.transient(root)
    dialog.grab_set()
    root.wait_window(dialog)

# ------------------------------
# Data helpers (bookmarks, notes, highlights, stats)
# ------------------------------
def load_json(filepath, default):
    if filepath.exists():
        with open(filepath, 'r') as f:
            return json.load(f)
    return default

def save_json(filepath, data):
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)

bookmarks = load_json(BOOKMARKS_FILE, {})      # {book_path: [{page, note, timestamp}]}
notes = load_json(NOTES_FILE, {})              # {book_path: [{page, note, timestamp}]}
highlights = load_json(HIGHLIGHTS_FILE, {})    # {book_path: [{page, text, timestamp}]}
stats = load_json(STATS_FILE, {"total_minutes": 0, "last_book": None, "last_page": None})

def update_reading_time(book_path, minutes=1):
    stats["total_minutes"] = stats.get("total_minutes", 0) + minutes
    save_json(STATS_FILE, stats)

def save_last_position(book_path, page):
    stats["last_book"] = book_path
    stats["last_page"] = page
    save_json(STATS_FILE, stats)

def get_last_position():
    return stats.get("last_book"), stats.get("last_page")

# ------------------------------
# Library management
# ------------------------------
def load_library():
    if LIBRARY_FILE.exists():
        with open(LIBRARY_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_library(lib):
    with open(LIBRARY_FILE, 'w') as f:
        json.dump(lib, f, indent=2)

library = load_library()

def refresh_library_list():
    library_listbox.delete(0, tk.END)
    for name in library:
        library_listbox.insert(tk.END, name)

def import_pdf(filepath=None):
    if not filepath:
        filepath = filedialog.askopenfilename(title="Select PDF file", filetypes=[("PDF files", "*.pdf")])
        if not filepath:
            return
    dest = APP_DIR / Path(filepath).name
    if dest.exists():
        answer = messagebox.askyesno("File exists", f"{dest.name} already exists. Overwrite?")
        if not answer:
            return
    shutil.copy2(filepath, dest)
    library[dest.name] = str(dest)
    save_library(library)
    refresh_library_list()
    messagebox.showinfo("Success", f"Imported: {dest.name}")

def batch_import():
    folder = filedialog.askdirectory(title="Select folder containing PDFs")
    if not folder:
        return
    imported = 0
    for f in Path(folder).glob("*.pdf"):
        try:
            dest = APP_DIR / f.name
            if not dest.exists():
                shutil.copy2(f, dest)
                library[dest.name] = str(dest)
                imported += 1
        except Exception as e:
            print(f"Error importing {f.name}: {e}")
    save_library(library)
    refresh_library_list()
    messagebox.showinfo("Batch Import", f"Imported {imported} new PDFs.")

# ------------------------------
# PDF Viewer with all features
# ------------------------------
class PDFViewer:
    def __init__(self, parent, pdf_path):
        self.parent = parent
        self.pdf_path = pdf_path
        self.doc = fitz.open(pdf_path)
        self.current_page = 0
        self.total_pages = len(self.doc)
        self.zoom = 1.0
        self.search_results = []
        self.current_result_index = -1
        self.focus_mode = False
        self.dark_mode = False
        
        self.window = tk.Toplevel(parent)
        self.window.title(f"Reading: {Path(pdf_path).name}")
        self.window.geometry("1100x750")
        self.window.configure(bg="#F9F6F0")
        
        # Load last position for this book
        last_book, last_page = get_last_position()
        if last_book == pdf_path and last_page is not None:
            self.current_page = min(last_page, self.total_pages - 1)
        
        # ------------------------------
        # Toolbar (two rows)
        # ------------------------------
        toolbar = tk.Frame(self.window, bg="#E8E0D5", height=50)
        toolbar.pack(side=tk.TOP, fill=tk.X)
        
        # Row 1: navigation
        row1 = tk.Frame(toolbar, bg="#E8E0D5")
        row1.pack(fill=tk.X, pady=2)
        tk.Button(row1, text="◀ Prev", command=self.prev_page, bg="#E6A157", fg="#1A4A4A", font=("Inter", 9, "bold")).pack(side=tk.LEFT, padx=5)
        self.page_label = tk.Label(row1, text="", bg="#E8E0D5", fg="#1A4A4A", font=("Inter", 10, "bold"))
        self.page_label.pack(side=tk.LEFT, padx=20)
        tk.Button(row1, text="Next ▶", command=self.next_page, bg="#E6A157", fg="#1A4A4A", font=("Inter", 9, "bold")).pack(side=tk.LEFT, padx=5)
        tk.Button(row1, text="Zoom +", command=self.zoom_in, bg="#1A4A4A", fg="#F9F6F0", font=("Inter", 9)).pack(side=tk.LEFT, padx=5)
        tk.Button(row1, text="Zoom -", command=self.zoom_out, bg="#1A4A4A", fg="#F9F6F0", font=("Inter", 9)).pack(side=tk.LEFT, padx=5)
        tk.Button(row1, text="🎯 Focus", command=self.toggle_focus, bg="#E6A157", fg="#1A4A4A", font=("Inter", 9)).pack(side=tk.LEFT, padx=5)
        tk.Button(row1, text="🌙 Dark", command=self.toggle_theme, bg="#1A4A4A", fg="#F9F6F0", font=("Inter", 9)).pack(side=tk.LEFT, padx=5)
        
        # Row 2: tools
        row2 = tk.Frame(toolbar, bg="#E8E0D5")
        row2.pack(fill=tk.X, pady=2)
        tk.Button(row2, text="🔖 Bookmark", command=self.add_bookmark, bg="#E6A157", fg="#1A4A4A", font=("Inter", 9)).pack(side=tk.LEFT, padx=5)
        tk.Button(row2, text="📝 Note", command=self.add_note, bg="#E6A157", fg="#1A4A4A", font=("Inter", 9)).pack(side=tk.LEFT, padx=5)
        tk.Button(row2, text="✍️ Highlight", command=self.add_highlight, bg="#E6A157", fg="#1A4A4A", font=("Inter", 9)).pack(side=tk.LEFT, padx=5)
        tk.Button(row2, text="📖 Dictionary", command=self.lookup_word, bg="#1A4A4A", fg="#F9F6F0", font=("Inter", 9)).pack(side=tk.LEFT, padx=5)
        
        # Search bar
        search_frame = tk.Frame(toolbar, bg="#E8E0D5")
        search_frame.pack(side=tk.RIGHT, padx=10)
        tk.Label(search_frame, text="Search:", bg="#E8E0D5", fg="#1A4A4A").pack(side=tk.LEFT)
        self.search_entry = tk.Entry(search_frame, width=20, font=("Inter", 9))
        self.search_entry.pack(side=tk.LEFT, padx=5)
        self.search_entry.bind("<Return>", lambda e: self.search_text())
        tk.Button(search_frame, text="Find", command=self.search_text, bg="#E6A157", fg="#1A4A4A", font=("Inter", 9)).pack(side=tk.LEFT, padx=2)
        tk.Button(search_frame, text="Next", command=self.next_result, bg="#1A4A4A", fg="#F9F6F0", font=("Inter", 9)).pack(side=tk.LEFT)
        
        # Canvas for PDF rendering
        canvas_frame = tk.Frame(self.window)
        canvas_frame.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(canvas_frame, bg="#F9F6F0")
        v_scroll = tk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        h_scroll = tk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)
        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        
        self.render_page()
        self.window.protocol("WM_DELETE_WINDOW", self.on_close)
    
    def render_page(self):
        page = self.doc[self.current_page]
        mat = fitz.Matrix(self.zoom, self.zoom)
        pix = page.get_pixmap(matrix=mat)
        img_data = pix.tobytes("ppm")
        img = Image.open(io.BytesIO(img_data))
        self.tk_img = ImageTk.PhotoImage(img)
        
        self.canvas.delete("all")
        self.canvas.config(scrollregion=(0, 0, self.tk_img.width(), self.tk_img.height()))
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.tk_img)
        
        # Highlight search results
        for (page_num, rects) in self.search_results:
            if page_num == self.current_page:
                for rect in rects:
                    x0 = rect.x0 * self.zoom
                    y0 = rect.y0 * self.zoom
                    x1 = rect.x1 * self.zoom
                    y1 = rect.y1 * self.zoom
                    self.canvas.create_rectangle(x0, y0, x1, y1, outline="yellow", width=2)
        
        self.page_label.config(text=f"Page {self.current_page+1}/{self.total_pages}")
        # Save position
        save_last_position(self.pdf_path, self.current_page)
    
    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self.render_page()
    
    def next_page(self):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self.render_page()
    
    def zoom_in(self):
        self.zoom = min(self.zoom + 0.2, 3.0)
        self.render_page()
    
    def zoom_out(self):
        self.zoom = max(self.zoom - 0.2, 0.5)
        self.render_page()
    
    def toggle_focus(self):
        self.focus_mode = not self.focus_mode
        if self.focus_mode:
            self.canvas.config(bg="#1e1e1e")
            self.window.attributes('-fullscreen', True)
        else:
            self.window.attributes('-fullscreen', False)
            self.canvas.config(bg="#F9F6F0")
    
    def toggle_theme(self):
        self.dark_mode = not self.dark_mode
        bg = "#1e1e1e" if self.dark_mode else "#F9F6F0"
        self.canvas.config(bg=bg)
    
    def search_text(self):
        query = self.search_entry.get().strip()
        if not query:
            return
        self.search_results = []
        for page_num in range(self.total_pages):
            page = self.doc[page_num]
            rects = page.search_for(query)
            if rects:
                self.search_results.append((page_num, rects))
        if not self.search_results:
            messagebox.showinfo("Not Found", f"No matches for '{query}'")
            self.current_result_index = -1
        else:
            self.current_result_index = 0
            self.go_to_result()
    
    def go_to_result(self):
        if self.current_result_index < 0 or self.current_result_index >= len(self.search_results):
            return
        page_num, _ = self.search_results[self.current_result_index]
        self.current_page = page_num
        self.render_page()
        self.page_label.config(text=f"Match {self.current_result_index+1}/{len(self.search_results)}")
        self.window.after(1500, lambda: self.page_label.config(text=f"Page {self.current_page+1}/{self.total_pages}"))
    
    def next_result(self):
        if not self.search_results:
            messagebox.showinfo("No search", "Perform a search first")
            return
        self.current_result_index = (self.current_result_index + 1) % len(self.search_results)
        self.go_to_result()
    
    def add_bookmark(self):
        note = simpledialog.askstring("Bookmark", "Optional note:", parent=self.window)
        book_path = self.pdf_path
        if book_path not in bookmarks:
            bookmarks[book_path] = []
        bookmarks[book_path].append({
            "page": self.current_page,
            "note": note if note else "",
            "timestamp": datetime.now().isoformat()
        })
        save_json(BOOKMARKS_FILE, bookmarks)
        messagebox.showinfo("Bookmark", f"Bookmarked page {self.current_page+1}")
    
    def add_note(self):
        note_text = simpledialog.askstring("Add Note", "Enter your note:", parent=self.window)
        if note_text:
            book_path = self.pdf_path
            if book_path not in notes:
                notes[book_path] = []
            notes[book_path].append({
                "page": self.current_page,
                "note": note_text,
                "timestamp": datetime.now().isoformat()
            })
            save_json(NOTES_FILE, notes)
            messagebox.showinfo("Note", "Note saved")
    
    def add_highlight(self):
        # Simple: user selects text (we use a dialog to paste)
        text = simpledialog.askstring("Highlight", "Paste or type the highlighted text:", parent=self.window)
        if text:
            book_path = self.pdf_path
            if book_path not in highlights:
                highlights[book_path] = []
            highlights[book_path].append({
                "page": self.current_page,
                "text": text,
                "timestamp": datetime.now().isoformat()
            })
            save_json(HIGHLIGHTS_FILE, highlights)
            messagebox.showinfo("Highlight", "Highlight saved")
    
    def lookup_word(self):
        word = simpledialog.askstring("Dictionary", "Enter word to look up:", parent=self.window)
        if word:
            # Simple offline dictionary (mock) – can be replaced with online API
            # For demonstration, we show a message.
            # Real implementation could use a local JSON word list.
            messagebox.showinfo("Dictionary", f"Definition of '{word}':\n(Offline dictionary not fully implemented. You can extend this.)")
    
    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")
    
    def on_close(self):
        # Update reading time (approx 1 minute per 5 pages as simple increment)
        update_reading_time(self.pdf_path, minutes=1)
        self.doc.close()
        self.window.destroy()

def open_selected_pdf():
    selection = library_listbox.curselection()
    if not selection:
        messagebox.showwarning("No selection", "Select a PDF from the library first.")
        return
    name = library_listbox.get(selection[0])
    pdf_path = library[name]
    if not os.path.exists(pdf_path):
        messagebox.showerror("File missing", f"PDF not found:\n{pdf_path}")
        del library[name]
        save_library(library)
        refresh_library_list()
        return
    viewer = PDFViewer(root, pdf_path)

# ------------------------------
# Admin Tunnel dialog (batch import, stats)
# ------------------------------
def show_admin_tunnel():
    admin_win = tk.Toplevel(root)
    admin_win.title("Admin Tunnel")
    admin_win.geometry("500x400")
    admin_win.configure(bg="#F9F6F0")
    tk.Label(admin_win, text="📦 Admin Book Tunnel", font=("Inter", 14, "bold"), bg="#F9F6F0", fg="#1A4A4A").pack(pady=10)
    tk.Button(admin_win, text="Batch Import PDFs from Folder", command=batch_import, bg="#E6A157", fg="#1A4A4A", font=("Inter", 10)).pack(pady=5)
    tk.Button(admin_win, text="View Reading Stats", command=show_stats, bg="#1A4A4A", fg="#F9F6F0", font=("Inter", 10)).pack(pady=5)
    tk.Button(admin_win, text="View Bookmarks", command=view_bookmarks, bg="#1A4A4A", fg="#F9F6F0", font=("Inter", 10)).pack(pady=5)
    tk.Button(admin_win, text="View Notes", command=view_notes, bg="#1A4A4A", fg="#F9F6F0", font=("Inter", 10)).pack(pady=5)
    tk.Button(admin_win, text="View Highlights", command=view_highlights, bg="#1A4A4A", fg="#F9F6F0", font=("Inter", 10)).pack(pady=5)

def show_stats():
    total_minutes = stats.get("total_minutes", 0)
    last_book = stats.get("last_book", "None")
    last_page = stats.get("last_page", 0)
    msg = f"Total reading time: {total_minutes} minutes\nLast opened: {Path(last_book).name if last_book else 'None'} (page {last_page+1})"
    messagebox.showinfo("Reading Statistics", msg)

def view_bookmarks():
    if not bookmarks:
        messagebox.showinfo("Bookmarks", "No bookmarks yet.")
        return
    win = tk.Toplevel(root)
    win.title("Bookmarks")
    win.geometry("600x400")
    text = tk.Text(win, wrap=tk.WORD)
    text.pack(fill=tk.BOTH, expand=True)
    for book_path, bmarks in bookmarks.items():
        text.insert(tk.END, f"\n📘 {Path(book_path).name}\n")
        for b in bmarks:
            text.insert(tk.END, f"  Page {b['page']+1}: {b['note']} ({b['timestamp'][:10]})\n")

def view_notes():
    if not notes:
        messagebox.showinfo("Notes", "No notes yet.")
        return
    win = tk.Toplevel(root)
    win.title("Notes")
    win.geometry("600x400")
    text = tk.Text(win, wrap=tk.WORD)
    text.pack(fill=tk.BOTH, expand=True)
    for book_path, note_list in notes.items():
        text.insert(tk.END, f"\n📘 {Path(book_path).name}\n")
        for n in note_list:
            text.insert(tk.END, f"  Page {n['page']+1}: {n['note']} ({n['timestamp'][:10]})\n")

def view_highlights():
    if not highlights:
        messagebox.showinfo("Highlights", "No highlights yet.")
        return
    win = tk.Toplevel(root)
    win.title("Highlights")
    win.geometry("600x400")
    text = tk.Text(win, wrap=tk.WORD)
    text.pack(fill=tk.BOTH, expand=True)
    for book_path, hl_list in highlights.items():
        text.insert(tk.END, f"\n📘 {Path(book_path).name}\n")
        for h in hl_list:
            text.insert(tk.END, f"  Page {h['page']+1}: \"{h['text']}\" ({h['timestamp'][:10]})\n")

def show_about():
    about_win = tk.Toplevel(root)
    about_win.title("About")
    about_win.geometry("400x250")
    about_win.configure(bg="#F9F6F0")
    tk.Label(about_win, text="Student Reader", font=("Inter", 16, "bold"), bg="#F9F6F0", fg="#1A4A4A").pack(pady=10)
    tk.Label(about_win, text="Version 2.0", font=("Inter", 10), bg="#F9F6F0", fg="#1A4A4A").pack()
    tk.Label(about_win, text="Developed by: Sharif Jogisharif", bg="#F9F6F0", fg="#1A4A4A").pack(pady=5)
    tk.Label(about_win, text="WhatsApp: +254712345678", bg="#F9F6F0", fg="#1A4A4A").pack()
    tk.Label(about_win, text="\nSecure offline PDF reader for students", bg="#F9F6F0", fg="#E6A157").pack()
    tk.Button(about_win, text="Close", command=about_win.destroy, bg="#E6A157", fg="#1A4A4A").pack(pady=10)

# ------------------------------
# Main UI
# ------------------------------
root = tk.Tk()
root.withdraw()

if needs_authentication():
    show_password_dialog()

root.deiconify()
root.title("Student Reader - Sharif")
root.geometry("1100x700")
root.configure(bg="#F9F6F0")  # cream background

# Left panel (Library) with deep teal accent
left_frame = tk.Frame(root, bg="#E8E0D5", width=280, relief=tk.FLAT)
left_frame.pack(side=tk.LEFT, fill=tk.Y, padx=0, pady=0)

tk.Label(left_frame, text="📚 My Library", font=("Inter", 16, "bold"), bg="#E8E0D5", fg="#1A4A4A").pack(pady=10)

library_listbox = tk.Listbox(left_frame, bg="#FFFFFF", fg="#1A4A4A", font=("Inter", 10), height=25, selectbackground="#E6A157")
library_listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

btn_frame = tk.Frame(left_frame, bg="#E8E0D5")
btn_frame.pack(fill=tk.X, padx=10, pady=5)
tk.Button(btn_frame, text="📂 Import PDF", command=import_pdf, bg="#E6A157", fg="#1A4A4A", font=("Inter", 10, "bold")).pack(side=tk.LEFT, padx=5)
tk.Button(btn_frame, text="📖 Open", command=open_selected_pdf, bg="#1A4A4A", fg="#F9F6F0", font=("Inter", 10, "bold")).pack(side=tk.LEFT, padx=5)

# Admin and About buttons
admin_btn = tk.Button(left_frame, text="⚙️ Admin Tunnel", command=show_admin_tunnel, bg="#E6A157", fg="#1A4A4A", font=("Inter", 10))
admin_btn.pack(pady=5, padx=10, fill=tk.X)
about_btn = tk.Button(left_frame, text="ℹ️ About", command=show_about, bg="#1A4A4A", fg="#F9F6F0", font=("Inter", 10))
about_btn.pack(pady=5, padx=10, fill=tk.X)

# Right panel (Welcome)
right_frame = tk.Frame(root, bg="#F9F6F0")
right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=20, pady=20)

welcome_text = f"""📖 Welcome to Student Reader

• Import PDFs using the left panel.
• Double-click a book to open it.
• While reading, use the toolbar to:
   - Navigate pages, zoom, focus mode, dark theme
   - Search text (Find / Next)
   - Add bookmarks, notes, highlights
   - Look up words (dictionary)
• Your reading position is saved automatically.
• Reading time is tracked.
• Admin Tunnel: batch import PDFs from a folder, view stats, bookmarks, notes, highlights.

Password (case-sensitive): {PASSWORD}
"""
welcome_label = tk.Label(right_frame, text=welcome_text, font=("Inter", 12), bg="#F9F6F0", fg="#1A4A4A", justify=tk.LEFT)
welcome_label.pack(pady=20, padx=20)

# Double-click to open
def on_listbox_doubleclick(event):
    open_selected_pdf()
library_listbox.bind("<Double-Button-1>", on_listbox_doubleclick)

refresh_library_list()
root.mainloop()    last = get_last_unlock()
    if last is None:
        return True
    last_time = datetime.fromisoformat(last)
    return datetime.now() - last_time > timedelta(days=2)

# ------------------------------
# Password dialog
# ------------------------------
def show_password_dialog():
    dialog = tk.Toplevel()
    dialog.title("Authentication")
    dialog.geometry("400x150")
    dialog.resizable(False, False)
    dialog.configure(bg="#2c3e50")
    
    tk.Label(dialog, text="Enter master password:", bg="#2c3e50", fg="white", font=("Arial", 12)).pack(pady=10)
    entry = tk.Entry(dialog, show="*", width=30, font=("Arial", 12))
    entry.pack(pady=5)
    error_label = tk.Label(dialog, text="", fg="red", bg="#2c3e50")
    error_label.pack()
    
    def verify():
        if entry.get() == PASSWORD:
            set_last_unlock()
            dialog.destroy()
        else:
            error_label.config(text="Incorrect password. Case-sensitive.")
    
    tk.Button(dialog, text="Unlock", command=verify, bg="#e74c3c", fg="white", font=("Arial", 10, "bold")).pack(pady=10)
    dialog.transient(root)
    dialog.grab_set()
    root.wait_window(dialog)

# ------------------------------
# Library management
# ------------------------------
def load_library():
    if LIBRARY_FILE.exists():
        with open(LIBRARY_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_library(lib):
    with open(LIBRARY_FILE, 'w') as f:
        json.dump(lib, f, indent=2)

library = load_library()

def refresh_library_list():
    library_listbox.delete(0, tk.END)
    for name in library:
        library_listbox.insert(tk.END, name)

def import_pdf():
    filepath = filedialog.askopenfilename(title="Select PDF file", filetypes=[("PDF files", "*.pdf")])
    if not filepath:
        return
    dest = APP_DIR / Path(filepath).name
    try:
        shutil.copy2(filepath, dest)
        library[dest.name] = str(dest)
        save_library(library)
        refresh_library_list()
        messagebox.showinfo("Success", f"Imported: {dest.name}")
    except Exception as e:
        messagebox.showerror("Error", f"Could not import:\n{e}")

# ------------------------------
# PDF Viewer with search
# ------------------------------
class PDFViewer:
    def __init__(self, parent, pdf_path):
        self.parent = parent
        self.pdf_path = pdf_path
        self.doc = fitz.open(pdf_path)
        self.current_page = 0
        self.total_pages = len(self.doc)
        self.zoom = 1.0
        self.search_results = []
        self.current_result_index = -1
        
        self.window = tk.Toplevel(parent)
        self.window.title(f"Reading: {Path(pdf_path).name}")
        self.window.geometry("1000x700")
        self.window.configure(bg="#2c3e50")
        
        # Toolbar
        toolbar = tk.Frame(self.window, bg="#34495e")
        toolbar.pack(side=tk.TOP, fill=tk.X, pady=5)
        
        tk.Button(toolbar, text="◀ Prev", command=self.prev_page, bg="#e67e22", fg="white").pack(side=tk.LEFT, padx=5)
        self.page_label = tk.Label(toolbar, text="", bg="#34495e", fg="white", font=("Arial", 10, "bold"))
        self.page_label.pack(side=tk.LEFT, padx=20)
        tk.Button(toolbar, text="Next ▶", command=self.next_page, bg="#e67e22", fg="white").pack(side=tk.LEFT, padx=5)
        tk.Button(toolbar, text="Zoom +", command=self.zoom_in, bg="#2ecc71", fg="white").pack(side=tk.LEFT, padx=5)
        tk.Button(toolbar, text="Zoom -", command=self.zoom_out, bg="#2ecc71", fg="white").pack(side=tk.LEFT, padx=5)
        
        # Search
        search_frame = tk.Frame(toolbar, bg="#34495e")
        search_frame.pack(side=tk.RIGHT, padx=10)
        tk.Label(search_frame, text="Search:", bg="#34495e", fg="white").pack(side=tk.LEFT)
        self.search_entry = tk.Entry(search_frame, width=20)
        self.search_entry.pack(side=tk.LEFT, padx=5)
        self.search_entry.bind("<Return>", lambda e: self.search_text())
        tk.Button(search_frame, text="Find", command=self.search_text, bg="#3498db", fg="white").pack(side=tk.LEFT)
        tk.Button(search_frame, text="Next", command=self.next_result, bg="#9b59b6", fg="white").pack(side=tk.LEFT, padx=5)
        
        # Canvas with scrollbars
        canvas_frame = tk.Frame(self.window)
        canvas_frame.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(canvas_frame, bg="#1e2a36")
        v_scroll = tk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        h_scroll = tk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)
        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        
        self.render_page()
    
    def render_page(self):
        page = self.doc[self.current_page]
        mat = fitz.Matrix(self.zoom, self.zoom)
        pix = page.get_pixmap(matrix=mat)
        img_data = pix.tobytes("ppm")
        img = Image.open(io.BytesIO(img_data))
        self.tk_img = ImageTk.PhotoImage(img)
        
        self.canvas.delete("all")
        self.canvas.config(scrollregion=(0, 0, self.tk_img.width(), self.tk_img.height()))
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.tk_img)
        
        # Highlight search results on this page
        for (page_num, rects) in self.search_results:
            if page_num == self.current_page:
                for rect in rects:
                    x0 = rect.x0 * self.zoom
                    y0 = rect.y0 * self.zoom
                    x1 = rect.x1 * self.zoom
                    y1 = rect.y1 * self.zoom
                    self.canvas.create_rectangle(x0, y0, x1, y1, outline="yellow", width=2)
        
        self.page_label.config(text=f"Page {self.current_page+1}/{self.total_pages}")
    
    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self.render_page()
    
    def next_page(self):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self.render_page()
    
    def zoom_in(self):
        self.zoom = min(self.zoom + 0.2, 3.0)
        self.render_page()
    
    def zoom_out(self):
        self.zoom = max(self.zoom - 0.2, 0.5)
        self.render_page()
    
    def search_text(self):
        query = self.search_entry.get().strip()
        if not query:
            return
        self.search_results = []
        for page_num in range(self.total_pages):
            page = self.doc[page_num]
            rects = page.search_for(query)
            if rects:
                self.search_results.append((page_num, rects))
        if not self.search_results:
            messagebox.showinfo("Not Found", f"No matches for '{query}'")
            self.current_result_index = -1
        else:
            self.current_result_index = 0
            self.go_to_result()
    
    def go_to_result(self):
        if self.current_result_index < 0 or self.current_result_index >= len(self.search_results):
            return
        page_num, _ = self.search_results[self.current_result_index]
        self.current_page = page_num
        self.render_page()
        self.page_label.config(text=f"Match {self.current_result_index+1}/{len(self.search_results)}")
        self.window.after(1500, lambda: self.page_label.config(text=f"Page {self.current_page+1}/{self.total_pages}"))
    
    def next_result(self):
        if not self.search_results:
            messagebox.showinfo("No search", "Perform a search first")
            return
        self.current_result_index = (self.current_result_index + 1) % len(self.search_results)
        self.go_to_result()
    
    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")
    
    def on_close(self):
        self.doc.close()
        self.window.destroy()

def open_selected_pdf():
    selection = library_listbox.curselection()
    if not selection:
        messagebox.showwarning("No selection", "Select a PDF from the library first.")
        return
    name = library_listbox.get(selection[0])
    pdf_path = library[name]
    if not os.path.exists(pdf_path):
        messagebox.showerror("File missing", f"PDF not found:\n{pdf_path}")
        del library[name]
        save_library(library)
        refresh_library_list()
        return
    viewer = PDFViewer(root, pdf_path)
    viewer.window.protocol("WM_DELETE_WINDOW", viewer.on_close)

# ------------------------------
# Main UI
# ------------------------------
root = tk.Tk()
root.withdraw()  # hide until password verified

if needs_authentication():
    show_password_dialog()

root.deiconify()
root.title("Student PDF Reader - Sharif")
root.geometry("1100x700")
root.configure(bg="#1e2a36")

# Left panel (Library)
left_frame = tk.Frame(root, bg="#2c3e50", width=250)
left_frame.pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=10)

tk.Label(left_frame, text="📚 My PDF Library", font=("Arial", 14, "bold"), bg="#2c3e50", fg="#ecf0f1").pack(pady=10)

library_listbox = tk.Listbox(left_frame, bg="#ecf0f1", fg="#2c3e50", font=("Arial", 10), height=25)
library_listbox.pack(fill=tk.BOTH, expand=True, pady=5)

btn_import = tk.Button(left_frame, text="📂 Import PDF", command=import_pdf, bg="#e67e22", fg="white", font=("Arial", 10, "bold"))
btn_import.pack(pady=5)
btn_open = tk.Button(left_frame, text="📖 Open Selected", command=open_selected_pdf, bg="#3498db", fg="white", font=("Arial", 10, "bold"))
btn_open.pack(pady=5)

# Right panel (Welcome)
right_frame = tk.Frame(root, bg="#1e2a36")
right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=10, pady=10)

welcome_text = f"""Welcome, Student!

• Import PDFs using the left panel.
• Double-click a file in the list to open it.
• While viewing a PDF, use the Search bar to find text.
• Zoom, previous/next, and result navigation available.

All documents are stored locally in:
{APP_DIR}

Password is case-sensitive: {PASSWORD}
"""
welcome_label = tk.Label(right_frame, text=welcome_text, font=("Arial", 11), bg="#1e2a36", fg="#bdc3c7", justify=tk.LEFT)
welcome_label.pack(pady=30, padx=20)

def on_listbox_doubleclick(event):
    open_selected_pdf()
library_listbox.bind("<Double-Button-1>", on_listbox_doubleclick)

refresh_library_list()
root.mainloop()
