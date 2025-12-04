import customtkinter
import tkinter as tk
from tkinter import filedialog, messagebox
import os
import shutil
import threading
import time
import datetime
import win32com.client
import pythoncom
import win32api
import queue

# Configuration
customtkinter.set_appearance_mode("Dark")
customtkinter.set_default_color_theme("blue")

# Shell Constants
BIF_RETURNONLYFSDIRS = 0x0001
BIF_DONTGOBELOWDOMAIN = 0x0002
BIF_STATUSTEXT = 0x0004
BIF_RETURNFSANCESTORS = 0x0008
BIF_EDITBOX = 0x0010
BIF_VALIDATE = 0x0020
BIF_NEWDIALOGSTYLE = 0x0040
BIF_BROWSEINCLUDEURLS = 0x0080
BIF_UAHINT = 0x0100
BIF_NONEWFOLDERBUTTON = 0x0200
BIF_NOTRANSLATETARGETS = 0x0400
BIF_BROWSEFORCOMPUTER = 0x1000
BIF_BROWSEFORPRINTER = 0x2000
BIF_BROWSEINCLUDEFILES = 0x4000
BIF_SHAREABLE = 0x8000

class MultiSelectDialog(customtkinter.CTkToplevel):
    def __init__(self, parent, title, items):
        super().__init__(parent)
        self.title(title)
        self.geometry("400x500")
        self.resizable(True, True)
        self.result = None
        
        self.lbl_instruction = customtkinter.CTkLabel(self, text="Select folders to backup:", font=("Roboto", 16))
        self.lbl_instruction.pack(pady=10)
        
        self.scroll_frame = customtkinter.CTkScrollableFrame(self)
        self.scroll_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        self.check_vars = {}
        for item in items:
            var = tk.BooleanVar(value=False)
            chk = customtkinter.CTkCheckBox(self.scroll_frame, text=item, variable=var)
            chk.pack(anchor="w", pady=2, padx=5)
            self.check_vars[item] = var
            
        self.btn_confirm = customtkinter.CTkButton(self, text="Confirm Selection", command=self.confirm)
        self.btn_confirm.pack(pady=10)
        
        # Make modal
        self.transient(parent)
        self.grab_set()
        self.focus_set()
        self.wait_window()
        
    def confirm(self):
        self.result = [item for item, var in self.check_vars.items() if var.get()]
        self.destroy()

class BackupApp(customtkinter.CTk):
    def __init__(self):
        super().__init__()

        # Window Setup
        self.title("CiderBridge")
        self.geometry("750x750")
        self.resizable(False, False)

        # Thread-safe communication
        self.msg_queue = queue.Queue()
        self.after(100, self.check_queue)

        # Variables
        self.source_path = tk.StringVar()
        self.dest_path = tk.StringVar()
        self.is_running = False
        self.total_files = 0
        self.total_bytes = 0
        self.copied_bytes = 0
        self.start_time = 0
        self.source_shell_item = None # For MTP devices
        self.failed_files = [] # List of (filename, error)
        self.selected_subfolders = [] # List of folder names to filter by
        self.mtp_breadcrumbs = [] # Path of folder names for thread-safe re-acquisition
        
        # Allowed Extensions (Lower case for comparison)
        self.allowed_extensions = {'.jpg', '.jpeg', '.png', '.heic', '.mov', '.mp4', '.avi', '.m4v'}

        self.create_widgets()

    def create_widgets(self):
        # Configure Theme
        customtkinter.set_appearance_mode("Dark")
        customtkinter.set_default_color_theme("dark-blue")
        
        # Main Layout Configuration
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0) # Warning
        self.grid_rowconfigure(1, weight=0) # Header
        self.grid_rowconfigure(2, weight=1) # Content
        
        # 1. Unlock Warning (Top Banner)
        self.warning_frame = customtkinter.CTkFrame(self, fg_color="#330000", corner_radius=0)
        self.warning_frame.grid(row=0, column=0, sticky="ew")
        
        self.lbl_warning = customtkinter.CTkLabel(
            self.warning_frame, 
            text="⚠ IMPORTANT: Please UNLOCK your iPhone screen before starting!", 
            text_color="#FF4444",
            font=("Segoe UI", 14, "bold")
        )
        self.lbl_warning.pack(pady=10)

        # 2. Header
        self.header_frame = customtkinter.CTkFrame(self, fg_color="transparent")
        self.header_frame.grid(row=1, column=0, pady=(20, 10))
        
        self.header_label = customtkinter.CTkLabel(
            self.header_frame, 
            text="CiderBridge", 
            font=("Segoe UI", 32, "bold"),
            text_color="white"
        )
        self.header_label.pack()
        
        self.sub_header = customtkinter.CTkLabel(
            self.header_frame,
            text="Securely transfer your photos & videos",
            font=("Segoe UI", 14),
            text_color="gray"
        )
        self.sub_header.pack()

        # 3. Content Area (Cards)
        self.content_frame = customtkinter.CTkFrame(self, fg_color="transparent")
        self.content_frame.grid(row=2, column=0, padx=40, pady=10, sticky="nsew")
        self.content_frame.grid_columnconfigure(0, weight=1)

        # --- Card: Source ---
        self.card_source = customtkinter.CTkFrame(self.content_frame, corner_radius=15)
        self.card_source.grid(row=0, column=0, pady=10, sticky="ew")
        
        self.lbl_source_title = customtkinter.CTkLabel(self.card_source, text="1. Source Device / Folder", font=("Segoe UI", 16, "bold"))
        self.lbl_source_title.pack(anchor="w", padx=20, pady=(15, 5))
        
        self.btn_source_mtp = customtkinter.CTkButton(
            self.card_source, 
            text="Select iPhone (MTP)", 
            command=self.select_source_mtp, 
            fg_color="#E0A800", 
            hover_color="#B08800",
            font=("Segoe UI", 14, "bold"),
            height=40
        )
        self.btn_source_mtp.pack(padx=20, pady=5, fill="x")

        self.btn_source = customtkinter.CTkButton(
            self.card_source, 
            text="Select PC Folder", 
            command=self.select_source, 
            fg_color="#444444", 
            hover_color="#666666",
            font=("Segoe UI", 14),
            height=30
        )
        self.btn_source.pack(padx=20, pady=(5, 15), fill="x")
        
        self.lbl_source = customtkinter.CTkLabel(self.card_source, textvariable=self.source_path, text_color="#AAAAAA", wraplength=500)
        self.lbl_source.pack(padx=20, pady=(0, 15), anchor="w")

        # --- Card: Destination ---
        self.card_dest = customtkinter.CTkFrame(self.content_frame, corner_radius=15)
        self.card_dest.grid(row=1, column=0, pady=10, sticky="ew")
        
        self.lbl_dest_title = customtkinter.CTkLabel(self.card_dest, text="2. Destination Folder", font=("Segoe UI", 16, "bold"))
        self.lbl_dest_title.pack(anchor="w", padx=20, pady=(15, 5))
        
        self.btn_dest = customtkinter.CTkButton(
            self.card_dest, 
            text="Select Destination", 
            command=self.select_dest,
            font=("Segoe UI", 14, "bold"),
            height=40
        )
        self.btn_dest.pack(padx=20, pady=5, fill="x")
        
        self.lbl_dest = customtkinter.CTkLabel(self.card_dest, textvariable=self.dest_path, text_color="#AAAAAA", wraplength=500)
        self.lbl_dest.pack(padx=20, pady=(0, 15), anchor="w")

        # --- Card: Progress & Action ---
        self.card_action = customtkinter.CTkFrame(self.content_frame, corner_radius=15)
        self.card_action.grid(row=2, column=0, pady=10, sticky="ew")

        self.lbl_status = customtkinter.CTkLabel(self.card_action, text="Ready to start", anchor="w", font=("Segoe UI", 14))
        self.lbl_status.pack(pady=(15, 5), padx=20, fill="x")

        self.progress_bar = customtkinter.CTkProgressBar(self.card_action, height=15, corner_radius=10)
        self.progress_bar.pack(pady=5, padx=20, fill="x")
        self.progress_bar.set(0)

        self.lbl_time = customtkinter.CTkLabel(self.card_action, text="Estimated time remaining: --:--", anchor="e", text_color="gray")
        self.lbl_time.pack(pady=(5, 10), padx=20, fill="x")

        self.btn_start = customtkinter.CTkButton(
            self.card_action, 
            text="START BACKUP", 
            command=self.start_backup_thread, 
            height=50, 
            font=("Segoe UI", 18, "bold"), 
            fg_color="#00C853", 
            hover_color="#009624",
            corner_radius=25
        )
        self.btn_start.pack(pady=(10, 20), padx=20, fill="x")

    def select_source(self):
        path = filedialog.askdirectory()
        if path:
            self.source_path.set(path)
            self.source_shell_item = None
            self.selected_subfolders = []

    def normalize_name(self, name):
        # Remove LTR/RTL marks and strip whitespace
        if not name: return ""
        return name.replace('\u200e', '').replace('\u200f', '').strip()

    def select_source_mtp(self):
        # Use Shell.Application to browse for folder (supports MTP)
        try:
            shell = win32com.client.Dispatch("Shell.Application")
            # 0 = Desktop, 17 = My Computer (Drives + MTP)
            folder = shell.BrowseForFolder(0, "Select PARENT Folder (e.g. Internal Storage) - Subfolders selection will appear NEXT", BIF_NEWDIALOGSTYLE | BIF_NONEWFOLDERBUTTON, 17)
            if folder:
                self.source_shell_item = folder.Self
                self.source_path.set(self.source_shell_item.Path)
                self.selected_subfolders = []
                
                # Build Breadcrumbs for thread-safe re-acquisition
                self.mtp_breadcrumbs = []
                curr = folder
                while curr:
                    title = curr.Title
                    # Stop if we hit the root or something empty
                    if not title: break
                    self.mtp_breadcrumbs.insert(0, self.normalize_name(title))
                    try:
                        curr = curr.ParentFolder
                    except:
                        break
                
                print(f"Selected MTP Path Breadcrumbs: {self.mtp_breadcrumbs}")
                
                # Check for subfolders to offer multi-select
                try:
                    # Give MTP a moment to populate
                    time.sleep(0.5)
                    
                    # Use the folder object directly from BrowseForFolder
                    items = folder.Items()
                    print(f"Found {items.Count} items in selected folder.")
                    
                    subfolders = [item.Name for item in items if item.IsFolder]
                    
                    if subfolders:
                        # Ask user if they want to select specific folders
                        dialog = MultiSelectDialog(self, "Select Subfolders", subfolders)
                        if dialog.result:
                            self.selected_subfolders = dialog.result
                            self.lbl_source.configure(text=f"{self.source_shell_item.Path} ({len(self.selected_subfolders)} folders selected)")
                        else:
                            # User cancelled, clear selection (process all)
                            self.selected_subfolders = []
                            self.lbl_source.configure(text=self.source_shell_item.Path)
                    else:
                        print("No subfolders found in selected folder.")
                except Exception as e:
                    print(f"Error checking subfolders: {e}")
                    messagebox.showwarning("Warning", f"Could not check for subfolders: {e}")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to open device selector: {e}")

    def select_dest(self):
        path = filedialog.askdirectory()
        if path:
            self.dest_path.set(path)

    def copy_file_chunked(self, src, dst):
        # Chunked copy to prevent memory spikes
        with open(src, 'rb') as fsrc:
            with open(dst, 'wb') as fdst:
                while True:
                    buf = fsrc.read(1024*1024) # 1MB chunks
                    if not buf:
                        break
                    fdst.write(buf)

    def start_backup_thread(self):
        if not self.source_path.get() or not self.dest_path.get():
            messagebox.showerror("Error", "Please select both source and destination directories.")
            return
        
        if self.is_running:
            return

        self.is_running = True
        self.btn_start.configure(state="disabled", text="Backing up...")
        self.progress_bar.set(0)
        
        # Pass breadcrumbs if MTP, otherwise None
        breadcrumbs = self.mtp_breadcrumbs if self.source_shell_item else None
        source_str = self.source_path.get()

        # Run in background thread
        thread = threading.Thread(target=self.run_backup, args=(source_str, breadcrumbs), daemon=True)
        thread.start()

    def run_backup(self, source_str, breadcrumbs):
        pythoncom.CoInitialize() # Initialize COM for this thread
        
        dest = self.dest_path.get()
        
        self.update_status("Scanning files...")
        self.copied_bytes = 0
        self.total_bytes = 0
        self.total_files = 0
        self.files_processed = 0
        self.failed_files = [] # Reset failures
        
        self.start_time = time.time()

        try:
            if breadcrumbs:
                # MTP / Shell Mode
                # Re-acquire using breadcrumbs to ensure thread safety
                print(f"Acquiring Shell Object using breadcrumbs: {breadcrumbs}")
                shell = win32com.client.Dispatch("Shell.Application")
                
                # Start at Desktop
                current_folder = shell.NameSpace(0) 
                
                # Traverse
                for name in breadcrumbs:
                    target_name = self.normalize_name(name)
                    current_title = self.normalize_name(current_folder.Title)
                    
                    # If we are already at this folder (e.g. Desktop == Desktop), skip
                    if target_name == current_title:
                        print(f"  Skipping '{target_name}' (already at '{current_title}')")
                        continue
                    
                    # Also skip explicit "Desktop" if we are at root, just in case
                    if target_name == "Desktop" and current_title == "Desktop":
                        continue
                        
                    print(f"  Looking for: '{target_name}' in '{current_title}'")
                    
                    found_sub = False
                    
                    # Optimization: Check if it's "This PC" (Namespace 17)
                    try:
                        my_computer = shell.NameSpace(17)
                        if self.normalize_name(my_computer.Title) == target_name:
                            print(f"    -> Found as 'This PC' (Namespace 17)")
                            current_folder = my_computer
                            found_sub = True
                    except: pass

                    if not found_sub:
                        items = current_folder.Items()
                        for item in items:
                            if self.normalize_name(item.Name) == target_name:
                                # Found the next step
                                if item.IsFolder:
                                    current_folder = item.GetFolder
                                    found_sub = True
                                    print(f"    -> Found match: {item.Name}")
                                    break
                    
                    if not found_sub:
                        print(f"Could not find '{target_name}' in '{current_title}'")
                        raise Exception(f"Could not navigate to '{name}'")
                
                # If we finished the loop, current_folder is our target
                self.backup_shell_mode(current_folder, dest)

            else:
                # Standard File System Mode
                self.backup_standard_mode(source_str, dest)
                
            self.finish_backup(success=True)
            
        except Exception as e:
            print(f"Backup Error: {e}")
            self.update_status(f"Error: {e}")
            self.finish_backup(success=False)
        finally:
            pythoncom.CoUninitialize()

    def backup_standard_mode(self, source, dest):
        # 1. Scan
        files_to_copy = []
        for root, dirs, files in os.walk(source):
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in self.allowed_extensions:
                    full_path = os.path.join(root, file)
                    try:
                        size = os.path.getsize(full_path)
                        files_to_copy.append((full_path, size))
                        self.total_bytes += size
                        self.total_files += 1
                    except: pass
        
        if not files_to_copy:
            self.update_status("No media files found (Standard Mode).")
            return

        # 2. Copy
        for src_file, size in files_to_copy:
            if not self.is_running: break
            
            rel_path = os.path.relpath(src_file, source)
            dest_file = os.path.join(dest, rel_path)
            dest_dir = os.path.dirname(dest_file)
            
            self.update_status(f"Copying: {os.path.basename(src_file)}")
            
            # RETRY LOGIC
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    os.makedirs(dest_dir, exist_ok=True)
                    self.copy_file_chunked(src_file, dest_file)
                    self.copied_bytes += size
                    self.files_processed += 1
                    self.update_progress(mode="bytes")
                    break # Success
                except Exception as e:
                    print(f"Failed: {src_file} - Attempt {attempt+1}/{max_retries} - {e}")
                    if attempt == max_retries - 1:
                        self.failed_files.append((os.path.basename(src_file), str(e)))

    def backup_shell_mode(self, source_item, dest_root):
        # source_item is now the unmarshaled COM object valid in this thread
        
        # We need to get the Folder object from the Item
        # Check if it's already a Folder object or an Item that has a GetFolder
        source_folder = None
        try:
            # Try treating it as a FolderItem
            source_folder = source_item.GetFolder
        except:
            # Maybe it's already a Folder object?
            source_folder = source_item

        if not source_folder:
             self.update_status("Error: Invalid source folder object.")
             return

        print(f"Processing Shell Folder: {source_folder.Title}")
        
        # Check if we have specific subfolders selected
        if self.selected_subfolders:
            print(f"Filtering by selected subfolders: {self.selected_subfolders}")
            items = source_folder.Items()
            for item in items:
                if not self.is_running: return
                if item.Name in self.selected_subfolders:
                    # Process this specific subfolder
                    new_dest_path = os.path.join(dest_root, item.Name)
                    os.makedirs(new_dest_path, exist_ok=True)
                    
                    # We need to get the Folder object for recursion
                    if item.IsFolder:
                         self.process_shell_folder(item.GetFolder, new_dest_path)
        else:
            # Process everything
            self.process_shell_folder(source_folder, dest_root)

    def process_shell_folder(self, folder_obj, current_dest_path):
        if not self.is_running: return

        try:
            items = folder_obj.Items()
            if items is None:
                print(f"Could not get items for folder: {folder_obj.Title}")
                return
                
            print(f"Processing folder: {folder_obj.Title} ({items.Count} items)")
            
            # Use iterator which is much faster (O(N)) than index access (O(N^2) on MTP)
            for item in items:
                if not self.is_running: return
                
                try:
                    name = item.Name
                    is_folder = item.IsFolder
                    
                    if is_folder:
                        print(f"  [FOLDER] Recursing into: {name}")
                        # Recursion
                        new_dest_path = os.path.join(current_dest_path, name)
                        os.makedirs(new_dest_path, exist_ok=True)
                        self.process_shell_folder(item.GetFolder, new_dest_path)
                    else:
                        # File
                        # Try to get extension from Name first
                        ext = os.path.splitext(name)[1].lower()
                        
                        # If no extension in Name, try Path (sometimes MTP paths include it)
                        if not ext:
                            try:
                                full_path = item.Path
                                ext = os.path.splitext(full_path)[1].lower()
                            except: pass
                        
                        item_type = item.Type
                        
                        # Filter Logic
                        is_allowed = ext in self.allowed_extensions
                        
                        # Fallback: If no extension, but Type looks like media (English/Hebrew common terms)
                        if not is_allowed and not ext:
                            # Basic keyword check for common media types
                            type_lower = item_type.lower()
                            if any(x in type_lower for x in ['image', 'video', 'movie', 'jpg', 'png', 'mov', 'mp4', 'תמונה', 'וידאו', 'סרט']):
                                is_allowed = True

                        if is_allowed:
                            self.update_status(f"Copying: {name}")
                            print(f"    -> MATCH! Attempting copy to {current_dest_path}")
                            
                            # RETRY LOGIC FOR MTP
                            max_retries = 3
                            for attempt in range(max_retries):
                                try:
                                    # For CopyHere to work reliably with MTP, we need the Destination FOLDER OBJECT
                                    # Constructing it via Shell.NameSpace is safest
                                    shell = win32com.client.Dispatch("Shell.Application")
                                    
                                    # Ensure destination directory exists
                                    if not os.path.exists(current_dest_path):
                                        os.makedirs(current_dest_path, exist_ok=True)
                                    
                                    # Normalize path for Windows (Shell API prefers backslashes)
                                    current_dest_path = os.path.abspath(current_dest_path)
                                        
                                    dest_folder_shell = None
                                    
                                    # Strategy 1: Standard NameSpace
                                    dest_folder_shell = shell.NameSpace(current_dest_path)
                                    
                                    # Strategy 2: Short Path (8.3)
                                    if not dest_folder_shell:
                                        try:
                                            short_path = win32api.GetShortPathName(current_dest_path)
                                            dest_folder_shell = shell.NameSpace(short_path)
                                        except: pass

                                    # Strategy 3: ParseName (Full Path)
                                    if not dest_folder_shell:
                                        try:
                                            desktop = shell.NameSpace(0)
                                            folder_item = desktop.ParseName(current_dest_path)
                                            if folder_item:
                                                dest_folder_shell = folder_item.GetFolder
                                        except: pass
                                        
                                    # Strategy 4: Parent Traversal (Most Robust for new folders/Unicode)
                                    if not dest_folder_shell:
                                        try:
                                            parent_path = os.path.dirname(current_dest_path)
                                            folder_name = os.path.basename(current_dest_path)
                                            
                                            parent_shell = shell.NameSpace(parent_path)
                                            if not parent_shell:
                                                # Try getting parent via ParseName
                                                desktop = shell.NameSpace(0)
                                                parent_item = desktop.ParseName(parent_path)
                                                if parent_item:
                                                    parent_shell = parent_item.GetFolder
                                            
                                            if parent_shell:
                                                folder_item = parent_shell.ParseName(folder_name)
                                                if folder_item:
                                                    dest_folder_shell = folder_item.GetFolder
                                        except Exception as e:
                                            print(f"    -> [DEBUG] Parent Traversal failed: {e}")

                                    if dest_folder_shell:
                                        # 16 = Yes to All, 256 = Simple Progress (optional)
                                        # We use 16 | 1024 (No UI) if possible, but MTP often ignores flags
                                        dest_folder_shell.CopyHere(item, 16)
                                        self.files_processed += 1
                                        self.update_progress(mode="count")
                                        print(f"    -> Copy command sent.")
                                        
                                        # THROTTLE: Sleep to let MTP breathe
                                        time.sleep(0.05)
                                        break # Success
                                    else:
                                        print(f"    -> ERROR: Could not get target Shell Folder for {current_dest_path}")
                                        raise Exception("Could not resolve destination folder")

                                except Exception as e:
                                    print(f"    -> FAILED to copy {name}: {e} (Attempt {attempt+1})")
                                    if attempt == max_retries - 1:
                                        self.failed_files.append((name, str(e)))
                                    time.sleep(1) # Wait before retry

                        else:
                            print(f"    -> SKIPPED: Extension {ext} not allowed.")
                
                except Exception as e:
                    print(f"Error processing item in {folder_obj.Title}: {e}")
                    # Don't stop the loop, just log and continue
                    continue

        except Exception as e:
            print(f"Error accessing folder {folder_obj.Title}: {e}")
            self.failed_files.append((folder_obj.Title, f"Folder Access Error: {e}"))

    def check_queue(self):
        try:
            while True:
                msg_type, data = self.msg_queue.get_nowait()
                if msg_type == "status":
                    self.lbl_status.configure(text=data)
                elif msg_type == "progress":
                    self.progress_bar.set(data)
                elif msg_type == "time":
                    self.lbl_time.configure(text=data)
                elif msg_type == "finish":
                    success = data
                    self.is_running = False
                    self.btn_start.configure(state="normal", text="Start Backup")
                    
                    # Show failed files report
                    if self.failed_files:
                        failed_msg = "\n".join([f"{f}: {e}" for f, e in self.failed_files[:10]])
                        if len(self.failed_files) > 10:
                            failed_msg += f"\n...and {len(self.failed_files) - 10} more."
                        messagebox.showwarning("Backup Completed with Errors", f"Backup completed, but some files failed:\n{failed_msg}")
                    elif success:
                        self.lbl_status.configure(text="Backup Completed Successfully!")
                        self.progress_bar.set(1)
                        self.lbl_time.configure(text="Done.")
                        messagebox.showinfo("Success", "Backup Completed Successfully!")
                    else:
                        messagebox.showerror("Error", "Backup stopped due to an error.")
        except queue.Empty:
            pass
        finally:
            self.after(100, self.check_queue)

    def update_status(self, text):
        self.msg_queue.put(("status", text))

    def update_progress(self, mode="bytes"):
        # For MTP, we might not have total bytes/files upfront easily.
        
        if mode == "bytes" and self.total_bytes > 0:
            percentage = self.copied_bytes / self.total_bytes
            self.msg_queue.put(("progress", percentage))
        elif mode == "count":
            self.msg_queue.put(("progress", 0.5)) # Indeterminate
            self.msg_queue.put(("time", f"Files Copied: {self.files_processed}"))
            return

        # Calculate ETA (only for bytes mode really)
        elapsed_time = time.time() - self.start_time
        if elapsed_time > 0 and self.copied_bytes > 0:
            speed = self.copied_bytes / elapsed_time
            remaining_bytes = self.total_bytes - self.copied_bytes
            eta_seconds = remaining_bytes / speed
            eta_str = str(datetime.timedelta(seconds=int(eta_seconds)))
            self.msg_queue.put(("time", f"Estimated time remaining: {eta_str}"))

    def finish_backup(self, success):
        self.msg_queue.put(("finish", success))

if __name__ == "__main__":
    app = BackupApp()
    app.mainloop()
