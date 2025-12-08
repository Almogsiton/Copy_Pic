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
            
            # Pre-scan for Image files (HEIC, JPG) if skipping live photos
            image_basenames = set()
            if skip_live_photos:
                for item in items:
                    try:
                        name = item.Name
                        if not name: continue
                        
                        # Check extension
                        ext = os.path.splitext(name)[1].lower()
                        if ext in ['.heic', '.jpg', '.jpeg']:
                             image_basenames.add(os.path.splitext(name)[0].lower())
                             continue

                        # If no extension, try to guess or just add it if it looks like a file
                        if not ext and not item.IsFolder:
                             # This is less reliable but safe for whitelist construction
                             image_basenames.add(name.lower())
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
                        try:
                            ext = os.path.splitext(name)[1].lower()
                        except: 
                            ext = ""
                            
                        item_basename = os.path.splitext(name)[0].lower()
                        
                        # Skip Live Photo .MOV if requested
                        # We check if the BASE name exists in our list of found images
                        if skip_live_photos and ext == '.mov' and item_basename in image_basenames:
                            logger.info(f"Skipping Live Photo video: {name}")
                            continue

                        # If extension is missing, we might want to copy it anyway and detect type later,
                        # OR try to infer it now.
                        inferred_ext = ext
                        if not inferred_ext:
                            try:
                                full_path = item.Path
                                inferred_ext = os.path.splitext(full_path)[1].lower()
                            except: pass
                        
                        item_type = item.Type
                        is_allowed = inferred_ext in ALLOWED_EXTENSIONS
                        
                        if not is_allowed and not inferred_ext:
                            # Fallback check on Type string
                            type_lower = item_type.lower()
                            if any(x in type_lower for x in ['image', 'video', 'movie', 'jpg', 'png', 'mov', 'mp4', 'heic', 'תמונה', 'וידאו', 'סרט']):
                                is_allowed = True

                        if is_allowed:
                            self.update_status(f"Copying: {name}")
                            
                            # Determine final target name
                            final_name = name
                            if inferred_ext and not name.lower().endswith(inferred_ext):
                                final_name = name + inferred_ext
                                logger.info(f"Target filename will be: {final_name}")

                            # Windows Shell CopyHere copies to folder, using the Item's internal name.
                            # We cannot easily rename DURING copy. 
                            # Strategy: Copy -> Verify -> Rename if component missing.
                            
                            logger.info(f"Attempting copy to {current_dest_path}")
                            
                            try:
                                shell = win32com.client.Dispatch("Shell.Application")
                                if not os.path.exists(current_dest_path):
                                    os.makedirs(current_dest_path, exist_ok=True)
                                
                                current_dest_path = os.path.abspath(current_dest_path)
                                dest_folder_shell = self.wait_for_shell_folder(shell, current_dest_path)

                                if dest_folder_shell:
                                    logger.debug(f"Sending CopyHere command for {name}...")
                                    # 1. Perform Copy
                                    dest_folder_shell.CopyHere(item, COPY_FLAGS_SILENT)
                                    
                                    expected_size = item.Size
                                    
                                    # 2. Wait/Verify & Rename Loop
                                    # The file might land as 'IMG_1234' (no ext) or 'IMG_1234.JPG'
                                    
                                    target_path_with_ext = os.path.join(current_dest_path, final_name)
                                    target_path_raw = os.path.join(current_dest_path, name)
                                    
                                    # Determine which file we actally look for to verify
                                    # We'll use a custom verification that looks for EITHER
                                    
                                    found_path = self.verify_and_fix_file(
                                        folder_path=current_dest_path,
                                        original_name=name,
                                        final_name=final_name,
                                        expected_size=expected_size
                                    )

                                    if found_path:
                                        self.files_processed += 1
                                        self.update_progress_count()
                                        logger.info(f"Copy verified: {os.path.basename(found_path)}")
                                    else:
                                        raise Exception("File verification failed (size mismatch or timeout)")
                                else:
                                    raise Exception("Could not resolve destination folder")

                            except Exception as e:
                                logger.error(f"FAILED to copy {name}: {e}")
                                self.cleanup_failed_copy(current_dest_path, name)
                                self.failed_files.append((name, str(e)))

                except Exception as e:
                    logger.error(f"Error processing item in {folder_obj.Title}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error accessing folder {folder_obj.Title}: {e}")
            self.failed_files.append((folder_obj.Title, f"Folder Access Error: {e}"))

    def verify_and_fix_file(self, folder_path: str, original_name: str, final_name: str, expected_size: int) -> Optional[str]:
        """
        Waits for the file to appear, stabilizes, and renames it if necessary.
        Returns the final path if successful, None otherwise.
        """
        start_time = time.time()
        timeout = 20  # generous timeout for MTP transfers
        
        path_raw = os.path.join(folder_path, original_name)
        path_final = os.path.join(folder_path, final_name)
        
        last_size = -1
        stable_count = 0
        
        while time.time() - start_time < timeout:
            if not self.is_running: return None
            
            # Check what actually exists
            exists_raw = os.path.exists(path_raw)
            exists_final = os.path.exists(path_final)
            
            if not exists_raw and not exists_final:
                time.sleep(0.5)
                continue
                
            current_path = path_final if exists_final else path_raw
            
            try:
                current_size = os.path.getsize(current_path)
                
                # If size is 0, it's still being created
                if current_size == 0:
                    time.sleep(0.5)
                    continue
                    
                # Check for stability
                if current_size == last_size:
                    stable_count += 1
                else:
                    last_size = current_size
                    stable_count = 0
                
                # If stable enough (MTP can be slow/bursty)
                if stable_count >= 2:
                    # Rename if needed (e.g. we have IMG_1234 but want IMG_1234.JPG)
                    if current_path != path_final:
                        try:
                            # If final path exists (collision?), try to remove it or skip
                            if os.path.exists(path_final):
                                logger.warning(f"Target path {path_final} already exists. Overwriting...")
                                os.remove(path_final)
                                
                            os.rename(current_path, path_final)
                            logger.info(f"Renamed {os.path.basename(current_path)} -> {os.path.basename(path_final)}")
                            current_path = path_final
                        except Exception as rename_err:
                            logger.error(f"Failed to rename file: {rename_err}")
                            # Continue with raw path if rename fails
                    
                    return current_path
                
                # Update progress UI
                if self.status_callback:
                     self.status_callback("file_progress", (original_name, current_size, expected_size))

            except Exception as e:
                logger.debug(f"Error checking file size: {e}")
                
            time.sleep(0.5)
            
        return None

    def cleanup_failed_copy(self, dest_dir: str, base_name: str):
        """Attempts to remove partial files after a failure."""
        try:
            candidates = []
            exact_path = os.path.join(dest_dir, base_name)
            if os.path.exists(exact_path):
                candidates.append(exact_path)
            
            # Also check for likely partials with similar names
            if os.path.exists(dest_dir):
                for f in os.listdir(dest_dir):
                    if f.startswith(base_name) and f != base_name:
                         # Very loose match to catch temp files
                         candidates.append(os.path.join(dest_dir, f))
            
            for cand in candidates:
                try:
                    os.remove(cand)
                    logger.info(f"Cleaned up partial: {cand}")
                except: pass
        except: pass

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
