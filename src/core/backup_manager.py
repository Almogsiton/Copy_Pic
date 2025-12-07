import time
import threading
import queue
import win32com.client
import pythoncom
from typing import List, Optional, Callable
from ..utils.constants import SSF_DESKTOP, SSF_DRIVES
from ..utils.logger import setup_logger
import os
from PIL import Image
import pillow_heif
from .file_system_handler import FileSystemHandler
from .mtp_handler import MTPHandler

logger = setup_logger("BackupManager")

class BackupManager:
    """
    Orchestrates the backup process, delegating to specific handlers for MTP or FileSystem operations.
    """
    def __init__(self, status_callback: Optional[Callable] = None):
        self.status_callback = status_callback
        self.is_running = False
        self.total_files = 0
        self.total_bytes = 0
        self.start_time = 0
        self.failed_files = []
        
        # Handlers
        self.fs_handler = FileSystemHandler(status_callback)
        self.mtp_handler = MTPHandler(status_callback)
        
        # Thread-safe communication
        self.msg_queue = queue.Queue()

    def start_backup(self, source: str, dest: str, breadcrumbs: Optional[List[str]] = None, selected_subfolders: Optional[List[str]] = None, skip_live_photos: bool = False):
        """
        Initiates the backup process in a separate thread.
        
        Args:
            source: Source path string (filesystem) or initial display string.
            dest: Destination folder path.
            breadcrumbs: List of folder names for MTP navigation (if source is MTP).
            selected_subfolders: List of specific subfolders to backup (whitelist).
            skip_live_photos: If True, tries to identify and skip Live Photo video components (context dependent).
        """
        if self.is_running: return
        
        self.is_running = True
        self.total_files = 0
        self.total_bytes = 0
        self.failed_files = []
        self.start_time = time.time()
        
        thread = threading.Thread(target=self.run_backup, args=(source, dest, breadcrumbs, selected_subfolders, skip_live_photos), daemon=True)
        thread.start()

    def stop_backup(self):
        """Signals the running backup process to stop."""
        self.is_running = False
        self.fs_handler.stop()
        self.mtp_handler.stop()

    def update_status(self, text: str):
        """
        Updates the status via callback and logs the message.
        
        Args:
            text: Status message to display/log.
        """
        if self.status_callback:
            self.status_callback("status", text)
        logger.info(text)

    def run_backup(self, source_str: str, dest: str, breadcrumbs: Optional[List[str]], selected_subfolders: Optional[List[str]], skip_live_photos: bool):
        """
        Main backup execution logic (threaded).
        Determines whether to use MTP (Shell) or FileSystem handler based on inputs.
        """
        pythoncom.CoInitialize()
        
        self.update_status("Scanning files...")
        
        try:
            if breadcrumbs:
                # MTP / Shell Mode
                logger.info(f"Acquiring Shell Object using breadcrumbs: {breadcrumbs}")
                shell = win32com.client.Dispatch("Shell.Application")
                current_folder = shell.NameSpace(SSF_DESKTOP)
                
                for name in breadcrumbs:
                    target_name = self.mtp_handler.normalize_name(name)
                    current_title = self.mtp_handler.normalize_name(current_folder.Title)
                    
                    if target_name == current_title: continue
                    if target_name == "Desktop" and current_title == "Desktop": continue
                        
                    logger.debug(f"Looking for: '{target_name}' in '{current_title}'")
                    found_sub = False
                    
                    try:
                        my_computer = shell.NameSpace(SSF_DRIVES)
                        if self.mtp_handler.normalize_name(my_computer.Title) == target_name:
                            current_folder = my_computer
                            found_sub = True
                    except: pass

                    if not found_sub:
                        items = current_folder.Items()
                        for item in items:
                            if self.mtp_handler.normalize_name(item.Name) == target_name:
                                if item.IsFolder:
                                    current_folder = item.GetFolder
                                    found_sub = True
                                    break
                    
                    if not found_sub:
                        raise Exception(f"Could not navigate to '{name}'")
                
                self.mtp_handler.backup_shell_mode(current_folder, dest, selected_subfolders, skip_live_photos)
                self.failed_files.extend(self.mtp_handler.failed_files)

            else:
                # Standard File System Mode
                self.fs_handler.backup_standard_mode(source_str, dest, self.total_bytes, self.start_time)
                self.failed_files.extend(self.fs_handler.failed_files)
            
            # Generate Failure Report
            if self.failed_files:
                report_path = os.path.join(dest, "failed_files.txt")
                try:
                    with open(report_path, "w", encoding="utf-8") as f:
                        f.write(f"Backup Failure Report - {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                        f.write("="*50 + "\n\n")
                        for name, error in self.failed_files:
                            f.write(f"File: {name}\nError: {error}\n" + "-"*30 + "\n")
                    logger.info(f"Failure report generated at: {report_path}")
                except Exception as report_err:
                    logger.error(f"Failed to create failure report: {report_err}")

            if self.status_callback:
                self.status_callback("finish", True)
            
        except Exception as e:
            logger.error(f"Backup Error: {e}")
            self.update_status(f"Error: {e}")
            self.failed_files.append(("General Error", str(e)))
            if self.status_callback:
                self.status_callback("finish", False)
        finally:
            self.is_running = False
            pythoncom.CoUninitialize()

    def scan_and_convert_heic(self, dest_folder: str):
        """
        Scans the destination folder for HEIC files and converts them to JPG depending on user settings.
        This runs as a secondary threaded process after backup completion.
        
        Args:
            dest_folder: The folder to scan recursively.
        """
        if self.is_running: return
        self.is_running = True
        
        thread = threading.Thread(target=self._run_conversion, args=(dest_folder,), daemon=True)
        thread.start()

    def _run_conversion(self, dest_folder: str):
        """
        Internal worker method for HEIC conversion.
        Iterates over files, converts using PIL/pillow_heif, and deletes originals.
        """
        try:
            heic_files = []
            self.update_status("Scanning for HEIC files...")
            
            # 1. Scan
            for root, dirs, files in os.walk(dest_folder):
                for file in files:
                    if file.lower().endswith('.heic'):
                        heic_files.append(os.path.join(root, file))
            
            total = len(heic_files)
            if total == 0:
                self.update_status("No HEIC files found.")
                if self.status_callback: self.status_callback("conversion_finish", True)
                return

            self.update_status(f"Found {total} HEIC files. Starting conversion...")
            
            # 2. Convert
            converted_count = 0
            for i, heic_path in enumerate(heic_files):
                if not self.is_running: break
                
                try:
                    # Create JPG path
                    jpg_path = os.path.splitext(heic_path)[0] + ".jpg"
                    
                    # Convert only if JPG doesn't exist (avoid overwriting existing if user had both)
                    if not os.path.exists(jpg_path):
                        self.update_status(f"Converting ({i+1}/{total}): {os.path.basename(heic_path)}")
                        
                        # Open HEIC
                        heif_file = pillow_heif.read_heif(heic_path)
                        image = Image.frombytes(
                            heif_file.mode, 
                            heif_file.size, 
                            heif_file.data,
                            "raw",
                            heif_file.mode,
                            heif_file.stride,
                        )
                        
                        # Save as JPG
                        image.save(jpg_path, "JPEG", quality=90)
                        converted_count += 1
                        
                        # DELETE ORIGINAL
                        try:
                            os.remove(heic_path)
                            logger.info(f"Deleted original: {heic_path}")
                        except Exception as del_err:
                            logger.error(f"Failed to delete original {heic_path}: {del_err}")

                        # Update Progress
                        if self.status_callback:
                            self.status_callback("progress", (i + 1) / total)
                    else:
                        logger.info(f"JPG already exists for {heic_path}, skipping conversion.")
                        # If JPG exists, do we delete HEIC? 
                        # User logic implies they want to replace it.
                        # Safe approach: If user ran this again, and JPG exists, maybe they expect HEIC gone.
                        # Let's delete it if the JPG is valid. But to be safe, maybe just skip for now unless explicit.
                        # Sticking to: Only delete if WE just converted it.
                        pass
                        
                except Exception as e:
                    logger.error(f"Failed to convert {heic_path}: {e}")
            
            self.update_status(f"Conversion complete. Converted {converted_count} files.")
            if self.status_callback: self.status_callback("conversion_finish", True)

        except Exception as e:
            logger.error(f"Conversion process error: {e}")
            self.update_status(f"Error during conversion: {e}")
            if self.status_callback: self.status_callback("conversion_finish", False)
        finally:
            self.is_running = False
