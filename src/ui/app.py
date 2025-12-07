import customtkinter
import tkinter as tk
from tkinter import filedialog, messagebox
import queue
import time
import os
import sys
from datetime import datetime

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

import win32com.client
from ..utils.constants import (
    BIF_NEWDIALOGSTYLE, BIF_NONEWFOLDERBUTTON,
    WINDOW_TITLE, WINDOW_GEOMETRY, THEME_MODE, THEME_COLOR,
    COLOR_WARNING_BG, COLOR_WARNING_TEXT, COLOR_INSTRUCTION_BG, COLOR_INSTRUCTION_TEXT,
    COLOR_BUTTON_MTP, COLOR_BUTTON_MTP_HOVER, COLOR_TEXT_GRAY, COLOR_TEXT_WHITE,
    FONT_WARNING, FONT_INSTRUCTION, FONT_HEADER_LARGE, FONT_HEADER_MEDIUM, FONT_NORMAL, FONT_BUTTON,
    QUEUE_CHECK_INTERVAL_MS, TIMER_UPDATE_INTERVAL_MS
)
from .dialogs import MultiSelectDialog, BackupModeDialog
from ..core.backup_manager import BackupManager

class BackupApp(customtkinter.CTk):
    """
    Main Application Window.
    Manages the UI layout, state, and coordinates with BackupManager.
    """
    def __init__(self):
        super().__init__()

        # Window Setup
        self.title(WINDOW_TITLE)
        self.geometry(WINDOW_GEOMETRY)
        self.resizable(True, True)

        # Thread-safe communication
        self.msg_queue = queue.Queue()
        self.after(100, self.check_queue)

        # Logic Manager
        self.backup_manager = BackupManager(status_callback=self.handle_manager_callback)

        # Variables
        self.source_path = tk.StringVar()
        self.dest_path = tk.StringVar()
        self.source_shell_item = None # For MTP devices
        self.selected_subfolders = [] # List of folder names to filter by
        self.mtp_breadcrumbs = [] # Path of folder names for thread-safe re-acquisition
        self.auto_convert_heic = False # Flag from Backup Mode selection
        
        self.timer_start_time = 0.0
        self.is_timer_running = False
        
        self.create_widgets()

    def handle_manager_callback(self, msg_type, data):
        self.msg_queue.put((msg_type, data))


    def create_widgets(self):
        """
        Orchestrates the UI construction by calling sub-methods for each section.
        """
        self._setup_theme()
        self._configure_layout()
        
        self.warning_frame = self._create_warning_banner()
        self.header_frame = self._create_header()
        self.content_frame = self._create_content_scroll_frame()
        
        # Add cards to content frame
        self.card_source = self._create_source_card(self.content_frame)
        self.card_dest = self._create_dest_card(self.content_frame)
        self.card_action = self._create_action_card(self.content_frame)

    def _setup_theme(self):
        customtkinter.set_appearance_mode(THEME_MODE)
        customtkinter.set_default_color_theme(THEME_COLOR)
        
        # Set Window Icon
        try:
            # When frozen, the asset is at root or specified folder
            # We will bundle 'src/assets/app_icon.ico' to 'src/assets/app_icon.ico'
            icon_location = resource_path(os.path.join("src", "assets", "app_icon.ico"))
            self.iconbitmap(icon_location)
        except Exception as e:
            print(f"Warning: Could not load icon: {e}")

    def _configure_layout(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0) # Warning
        self.grid_rowconfigure(1, weight=0) # Header
        self.grid_rowconfigure(2, weight=1) # Content

    def _create_warning_banner(self):
        frame = customtkinter.CTkFrame(self, fg_color=COLOR_WARNING_BG, corner_radius=0)
        frame.grid(row=0, column=0, sticky="ew")
        
        lbl_warning = customtkinter.CTkLabel(
            frame, 
            text="⚠ IMPORTANT: Please UNLOCK your iPhone screen before starting!", 
            text_color=COLOR_WARNING_TEXT,
            font=FONT_WARNING
        )
        lbl_warning.pack(pady=(10, 5))

        lbl_instruction = customtkinter.CTkLabel(
            frame,
            text="CRITICAL: Go to Settings > Apps > Photos > Transfer to Mac or PC > Select 'Keep Originals'",
            text_color=COLOR_INSTRUCTION_TEXT,
            fg_color=COLOR_INSTRUCTION_BG,
            font=FONT_INSTRUCTION,
            corner_radius=6
        )
        lbl_instruction.pack(pady=(0, 10), padx=10, fill="x")
        return frame

    def _create_header(self):
        frame = customtkinter.CTkFrame(self, fg_color="transparent")
        frame.grid(row=1, column=0, pady=(5, 5))
        
        lbl_title = customtkinter.CTkLabel(
            frame, 
            text=WINDOW_TITLE, 
            font=FONT_HEADER_LARGE,
            text_color=COLOR_TEXT_WHITE
        )
        lbl_title.pack()
        
        lbl_subtitle = customtkinter.CTkLabel(
            frame,
            text="Securely transfer your photos & videos",
            font=FONT_NORMAL,
            text_color="gray"
        )
        lbl_subtitle.pack()
        return frame

    def _create_content_scroll_frame(self):
        frame = customtkinter.CTkScrollableFrame(self, fg_color="transparent")
        frame.grid(row=2, column=0, padx=20, pady=5, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        return frame

    def _create_source_card(self, parent):
        card = customtkinter.CTkFrame(parent, corner_radius=15)
        card.grid(row=0, column=0, pady=10, sticky="ew")
        
        lbl_title = customtkinter.CTkLabel(card, text="1. Source Device / Folder", font=FONT_HEADER_MEDIUM)
        lbl_title.pack(anchor="w", padx=20, pady=(15, 5))
        
        btn_mtp = customtkinter.CTkButton(
            card, 
            text="Select iPhone (MTP)", 
            command=self.select_source_mtp, 
            fg_color=COLOR_BUTTON_MTP, 
            hover_color=COLOR_BUTTON_MTP_HOVER,
            font=FONT_BUTTON,
            height=40
        )
        btn_mtp.pack(padx=20, pady=5, fill="x")
        
        self.lbl_source = customtkinter.CTkLabel(card, textvariable=self.source_path, text_color=COLOR_TEXT_GRAY, wraplength=500)
        self.lbl_source.pack(padx=20, pady=(0, 15), anchor="w")
        return card

    def _create_dest_card(self, parent):
        card = customtkinter.CTkFrame(parent, corner_radius=15)
        card.grid(row=1, column=0, pady=10, sticky="ew")
        
        lbl_title = customtkinter.CTkLabel(card, text="2. Destination Folder", font=FONT_HEADER_MEDIUM)
        lbl_title.pack(anchor="w", padx=20, pady=(15, 5))
        
        btn_dest = customtkinter.CTkButton(
            card, 
            text="Select Destination", 
            command=self.select_dest,
            font=FONT_BUTTON,
            height=40
        )
        btn_dest.pack(padx=20, pady=5, fill="x")
        
        self.lbl_dest = customtkinter.CTkLabel(card, textvariable=self.dest_path, text_color=COLOR_TEXT_GRAY, wraplength=500)
        self.lbl_dest.pack(padx=20, pady=(0, 15), anchor="w")
        return card

    def _create_action_card(self, parent):
        card = customtkinter.CTkFrame(parent, corner_radius=15)
        card.grid(row=2, column=0, pady=10, sticky="ew")

        self.lbl_status = customtkinter.CTkLabel(card, text="Ready to start", anchor="w", font=FONT_WARNING)
        self.lbl_status.pack(pady=(15, 5), padx=20, fill="x")

        self.progress_bar = customtkinter.CTkProgressBar(card, height=15, corner_radius=10)
        self.progress_bar.pack(pady=5, padx=20, fill="x")
        self.progress_bar.set(0)

        self.lbl_time = customtkinter.CTkLabel(card, text="", anchor="e", text_color="gray")
        self.lbl_time.pack(pady=(5, 10), padx=20, fill="x")

        self.btn_start = customtkinter.CTkButton(
            card, 
            text="START BACKUP", 
            command=self.start_backup, 
            height=50, 
            font=("Segoe UI", 18, "bold"), 
            fg_color="#00C853", 
            hover_color="#009624",
            corner_radius=25
        )
        self.btn_start.pack(pady=(10, 20), padx=20, fill="x")
        return card



    def normalize_name(self, name):
        # Remove LTR/RTL marks and strip whitespace
        if not name: return ""
        return name.replace('\u200e', '').replace('\u200f', '').strip()

    def select_source_mtp(self):
        """
        Opens a Folder selection dialog configured for MTP devices (Shell Namespace).
        Allows selecting 'This PC' -> 'iPhone' -> 'Internal Storage'.
        If subfolders exists, opens a MultiSelectDialog to filter them.
        """
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
                
                # Check for subfolders to offer multi-select
                try:
                    # Give MTP a moment to populate
                    time.sleep(0.5)
                    
                    # Use the folder object directly from BrowseForFolder
                    items = folder.Items()
                    
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
                        pass
                except Exception as e:
                    print(f"Error checking subfolders: {e}")
                    messagebox.showwarning("Warning", f"Could not check for subfolders: {e}")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to open device selector: {e}")

    def select_dest(self):
        """Opens a standard directory selector for the destination."""
        path = filedialog.askdirectory()
        if path:
            self.dest_path.set(path)

    def start_backup(self):
        """
        Validates inputs, prompts for mode (Optimize vs Keep Originals), 
        creates the date-stamped destination folder, and initiates the backup process.
        """
        if not self.source_path.get() or not self.dest_path.get():
            messagebox.showerror("Error", "Please select both source and destination directories.")
            return
        
        if self.backup_manager.is_running:
            return

        # Demand Mode Selection
        dialog = BackupModeDialog(self)
        if not dialog.result:
            return # User cancelled
            
        convert_heic, skip_live_photos = dialog.result
        self.auto_convert_heic = convert_heic

        self.btn_start.configure(state="disabled", text="Backing up...")
        self.progress_bar.set(0)
        
        # Pass breadcrumbs if MTP, otherwise None
        breadcrumbs = self.mtp_breadcrumbs if self.source_shell_item else None
        source_str = self.source_path.get()
        dest_str = self.dest_path.get()
        # Create Date-Based Subfolder
        date_str = datetime.now().strftime("%d-%m-%Y")
        
        # Check if the user selected a folder that IS ALREADY the date folder
        if os.path.basename(dest_str) == date_str:
            final_dest = dest_str
        else:
            final_dest = os.path.join(dest_str, date_str)
        
        try:
            os.makedirs(final_dest, exist_ok=True)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to create date folder: {e}")
            self.btn_start.configure(state="normal", text="START BACKUP")
            return

        self.actual_dest_path = final_dest  # Store for later use
        
        # Start Timer
        self.timer_start_time = time.time()
        self.is_timer_running = True
        self.update_timer()

        self.backup_manager.start_backup(source_str, final_dest, breadcrumbs, self.selected_subfolders, skip_live_photos)

    def update_timer(self):
        if not self.is_timer_running:
            return
            
        elapsed = time.time() - self.timer_start_time
        mins, secs = divmod(int(elapsed), 60)
        hours, mins = divmod(mins, 60)
        
        if hours > 0:
            time_str = f"{hours:02d}:{mins:02d}:{secs:02d}"
        else:
            time_str = f"{mins:02d}:{secs:02d}"
            
        self.lbl_time.configure(text=f"Time Elapsed: {time_str}")
        self.after(1000, self.update_timer)



    def check_queue(self):
        """
        Polls the thread-safe message queue for updates from the backup thread.
        Dispatches messages to appropriate handler methods.
        """
        try:
            while True:
                try:
                    msg_type, data = self.msg_queue.get_nowait()
                except queue.Empty:
                    break

                try:
                    if msg_type == "status":
                        self.lbl_status.configure(text=data)
                    elif msg_type == "progress":
                        self.progress_bar.set(data)
                    elif msg_type == "file_progress":
                        self._handle_file_progress(data)
                    elif msg_type == "time":
                        self.lbl_time.configure(text=data)
                    elif msg_type == "finish":
                        self._handle_finish_message(data)
                    elif msg_type == "conversion_finish":
                        self._handle_conversion_finish(data)

                except Exception as e:
                    import traceback
                    print(f"ERROR in check_queue message processing: {e}")
                    traceback.print_exc()

        finally:
            self.after(QUEUE_CHECK_INTERVAL_MS, self.check_queue)

    def _handle_file_progress(self, data):
        filename, current, total = data
        if total > 0:
            percent = int((current / total) * 100)
            self.lbl_status.configure(text=f"Copying: {filename} ({percent}%)")
        else:
            mb = current / (1024 * 1024)
            self.lbl_status.configure(text=f"Copying: {filename} ({mb:.1f} MB)")

    def _format_total_time(self):
        elapsed = time.time() - self.timer_start_time
        mins, secs = divmod(int(elapsed), 60)
        hours, mins = divmod(mins, 60)
        if hours > 0:
            return f"{hours:02d}h {mins:02d}m {secs:02d}s"
        return f"{mins:02d}m {secs:02d}s"

    def _handle_finish_message(self, success):
        total_time_str = self._format_total_time()
        
        dest_path = self.actual_dest_path
        should_convert = False
            
        if success and self.auto_convert_heic:
            try:
                for root, dirs, files in os.walk(dest_path):
                    if any(f.lower().endswith('.heic') for f in files):
                        should_convert = True
                        break
            except Exception:
                pass
        
        # Stop timer ONLY if we are NOT proceeding to conversion
        if not should_convert:
             self.is_timer_running = False
        
        if success:
            self.lbl_status.configure(text=f"Backup Completed in {total_time_str}! Finalizing...")
            self.progress_bar.set(1)
            self.lbl_time.configure(text=f"Total Time: {total_time_str}")
            
            self._show_failed_files_if_any(total_time_str)
            
            # LOGIC BRANCH: Optimize vs Keep Originals
            if self.auto_convert_heic:
                self._handle_auto_convert_logic(dest_path, should_convert, total_time_str)
            else:
                self._enable_ui_post_backup()
                messagebox.showinfo("Success", f"Backup Completed Successfully!\nTotal Time: {total_time_str}")
            
        else:
            self.is_timer_running = False
            self._enable_ui_post_backup()
            messagebox.showerror("Error", f"Backup stopped due to an error.\nTime Elapsed: {total_time_str}")

    def _show_failed_files_if_any(self, total_time_str):
        if self.backup_manager.failed_files:
            failed_msg = "\n".join([f"{f}: {e}" for f, e in self.backup_manager.failed_files[:10]])
            if len(self.backup_manager.failed_files) > 10:
                failed_msg += f"\n...and {len(self.backup_manager.failed_files) - 10} more."
            messagebox.showwarning("Backup Completed with Errors", f"Backup completed in {total_time_str}, but some files failed:\n{failed_msg}")

    def _handle_auto_convert_logic(self, dest_path, should_convert, total_time_str):
        if should_convert:
            self.btn_start.configure(state="disabled", text="Converting...")
            self.lbl_status.configure(text="Optimizing: Converting HEIC to JPG...")
            self.progress_bar.set(0)
            self.backup_manager.scan_and_convert_heic(dest_path)
        else:
            self._enable_ui_post_backup()
            messagebox.showinfo("Success", f"Backup & Optimization Completed Successfully!\nTotal Time: {total_time_str}")

    def _handle_conversion_finish(self, success):
        self.is_timer_running = False
        total_time_str = self._format_total_time()
        self._enable_ui_post_backup()
        
        if success:
            self.lbl_status.configure(text=f"Optimization Completed in {total_time_str}!")
            self.lbl_time.configure(text=f"Total Time: {total_time_str}")
            messagebox.showinfo("Success", f"Conversion Completed Successfully!\nTotal Time: {total_time_str}")
        else:
            self.lbl_status.configure(text="Conversion Failed.")
            messagebox.showerror("Error", f"Conversion process failed.\nTotal Time: {total_time_str}")

    def _enable_ui_post_backup(self):
        self.btn_start.configure(state="normal", text="Start Backup")
