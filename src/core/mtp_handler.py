import os
import time
import win32com.client
from typing import List, Tuple, Callable, Optional
from ..utils.constants import (
    ALLOWED_EXTENSIONS, 
    COPY_FLAGS_SILENT, 
    MAX_RETRIES, 
    RETRY_DELAY,
    VERIFY_POLL_INTERVAL
)
from ..utils.logger import setup_logger
from .file_system_handler import FileSystemHandler

logger = setup_logger("MTPHandler")

class MTPHandler:
    """
    Handles file transfer operations from MTP devices (like iPhone) using the Windows Shell COM interface.
    """
    def __init__(self, status_callback: Optional[Callable] = None):
        self.status_callback = status_callback
        self.is_running = False
        self.files_processed = 0
        self.failed_files: List[Tuple[str, str]] = []

    def update_status(self, text: str):
        """Standard status callback wrapper."""
        if self.status_callback:
            self.status_callback("status", text)
        logger.info(text)

    def update_progress_count(self):
        """Updates the running count of copied files."""
        if self.status_callback:
            self.status_callback("progress", 0.5) # Indeterminate
            self.status_callback("time", f"Files Copied: {self.files_processed}")

    def stop(self):
        """Signals the copy process to stop."""
        self.is_running = False

    def normalize_name(self, name: str) -> str:
        """Removes hidden unicode markers often found in MTP folder names."""
        if not name: return ""
        return name.replace('\u200e', '').replace('\u200f', '').strip()

    def backup_shell_mode(self, source_item, dest_root: str, selected_subfolders: Optional[List[str]] = None, skip_live_photos: bool = False):
        """
        Main entry point for MTP backup using Shell.Application.
        
        Args:
            source_item: The ShellFolderItem representing the source root (e.g. 'Internal Storage').
            dest_root: Local filesystem path to backup to.
            selected_subfolders: Optional whitelist of subfolder names to include.
            skip_live_photos: Whether to skip .MOV components of Live Photos.
        """
        self.is_running = True
        source_folder = None
        try:
            source_folder = source_item.GetFolder
        except:
            source_folder = source_item

        if not source_folder:
             self.update_status("Error: Invalid source folder object.")
             return

        logger.info(f"Processing Shell Folder: {source_folder.Title}")
        
        if selected_subfolders:
            logger.info(f"Filtering by selected subfolders: {selected_subfolders}")
            items = source_folder.Items()
            for item in items:
                if not self.is_running: return
                if item.Name in selected_subfolders:
                    new_dest_path = os.path.join(dest_root, item.Name)
                    os.makedirs(new_dest_path, exist_ok=True)
                    if item.IsFolder:
                         self.process_shell_folder(item.GetFolder, new_dest_path, skip_live_photos)
        else:
            self.process_shell_folder(source_folder, dest_root, skip_live_photos)

    def process_shell_folder(self, folder_obj, current_dest_path: str, skip_live_photos: bool = False):
        """
        Recursively processes an MTP folder.
        Scanning items, filtering by extension, and copying files.
        """
        if not self.is_running: return

        try:
            items = folder_obj.Items()
            if items is None: return
                
            logger.info(f"Processing folder: {folder_obj.Title} ({items.Count} items)")
            
            # Pre-scan for HEIC files if skipping live photos
            heic_basenames = set()
            if skip_live_photos:
                for item in items:
                    try:
                        name = item.Name
                        if name.lower().endswith('.heic'):
                            heic_basenames.add(os.path.splitext(name)[0].lower())
                    except: pass
            
            for item in items:
                if not self.is_running: return
                
                try:
                    name = item.Name
                    is_folder = item.IsFolder
                    
                    if is_folder:
                        logger.debug(f"Recursing into: {name}")
                        new_dest_path = os.path.join(current_dest_path, name)
                        os.makedirs(new_dest_path, exist_ok=True)
                        self.process_shell_folder(item.GetFolder, new_dest_path, skip_live_photos)
                    else:
                        ext = os.path.splitext(name)[1].lower()
                        item_basename = os.path.splitext(name)[0].lower()
                        
                        # Skip Live Photo .MOV if requested
                        if skip_live_photos and ext == '.mov' and item_basename in heic_basenames:
                            logger.info(f"Skipping Live Photo video: {name}")
                            continue

                        if not ext:
                            try:
                                full_path = item.Path
                                ext = os.path.splitext(full_path)[1].lower()
                            except: pass
                        
                        item_type = item.Type
                        is_allowed = ext in ALLOWED_EXTENSIONS
                        
                        if not is_allowed and not ext:
                            type_lower = item_type.lower()
                            if any(x in type_lower for x in ['image', 'video', 'movie', 'jpg', 'png', 'mov', 'mp4', 'תמונה', 'וידאו', 'סרט']):
                                is_allowed = True

                        if is_allowed:
                            # Fix filename if extension is missing from name but present in properties
                            if ext and not name.lower().endswith(ext):
                                name += ext
                                logger.info(f"Corrected filename to: {name}")

                            self.update_status(f"Copying: {name}")
                            logger.info(f"Attempting copy to {current_dest_path}")
                            
                            try:
                                shell = win32com.client.Dispatch("Shell.Application")
                                if not os.path.exists(current_dest_path):
                                    os.makedirs(current_dest_path, exist_ok=True)
                                
                                current_dest_path = os.path.abspath(current_dest_path)
                                dest_folder_shell = self.wait_for_shell_folder(shell, current_dest_path)

                                if dest_folder_shell:
                                    logger.debug(f"Sending CopyHere command for {name}...")
                                    dest_folder_shell.CopyHere(item, COPY_FLAGS_SILENT)
                                    
                                    expected_size = item.Size
                                    dest_file_path = os.path.join(current_dest_path, name)
                                    
                                    progress_cb = lambda c, t: self.status_callback("file_progress", (name, c, t)) if self.status_callback else None
                                    
                                    if FileSystemHandler.verify_file_copy(dest_file_path, expected_size, is_running_check=lambda: self.is_running, progress_callback=progress_cb):
                                        self.files_processed += 1
                                        self.update_progress_count()
                                        logger.info(f"Copy verified: {name}")
                                    else:
                                        raise Exception("File verification failed (size mismatch or timeout)")
                                else:
                                    raise Exception("Could not resolve destination folder")

                            except Exception as e:
                                logger.error(f"FAILED to copy {name}: {e}")
                                
                                # Cleanup failed partial copy
                                try:
                                    candidates = []
                                    dest_dir = current_dest_path
                                    base_name = name
                                    
                                    exact_path = os.path.join(dest_dir, base_name)
                                    if os.path.exists(exact_path):
                                        candidates.append(exact_path)
                                    
                                    if os.path.exists(dest_dir):
                                        try:
                                            for f in os.listdir(dest_dir):
                                                if f.startswith(base_name) and f != base_name:
                                                    if os.path.splitext(f)[0] == base_name:
                                                        candidates.append(os.path.join(dest_dir, f))
                                        except: pass
                                    
                                    if candidates:
                                        for cand in candidates:
                                            logger.info(f"Cleaning up partial file: {cand}")
                                            try:
                                                os.remove(cand)
                                            except Exception as del_err:
                                                logger.warning(f"Failed to remove {cand}: {del_err}")

                                except Exception as cleanup_error:
                                    logger.warning(f"Failed to cleanup partial file: {cleanup_error}")

                                self.failed_files.append((name, str(e)))

                except Exception as e:
                    logger.error(f"Error processing item in {folder_obj.Title}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error accessing folder {folder_obj.Title}: {e}")
            self.failed_files.append((folder_obj.Title, f"Folder Access Error: {e}"))

    def wait_for_shell_folder(self, shell, path: str, timeout: int = 5):
        logger.debug(f"Resolving '{path}'")
        start = time.time()
        while time.time() - start < timeout:
            folder = shell.NameSpace(path)
            if folder:
                try:
                    folder_path = folder.Self.Path
                    if os.path.normpath(folder_path) == os.path.normpath(path):
                        return folder
                except Exception as e:
                    logger.debug(f"Error checking folder path: {e}")
                    return folder
            
            try:
                parent_path = os.path.dirname(path)
                folder_name = os.path.basename(path)
                parent = shell.NameSpace(parent_path)
                if parent:
                    item = parent.ParseName(folder_name)
                    if item and item.IsFolder:
                        return item.GetFolder
            except: pass
            time.sleep(VERIFY_POLL_INTERVAL)
        return None
