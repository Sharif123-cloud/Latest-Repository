import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import json
import os
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
import fitz  # PyMuPDF
from PIL import Image, ImageTk
import io
import shutil

# ------------------------------
# Configuration
# ------------------------------
APP_DIR = Path.home() / "StudentReader"
APP_DIR.mkdir(exist_ok=True)
CONFIG_FILE = APP_DIR / "config.json"
LIBRARY_FILE = APP_DIR / "library.json"
PASSWORD = "SSERUNJOGISHARIF47@GMAIL.COM"  # case-sensitive

# ------------------------------
# Security functions
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
