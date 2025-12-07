import os
import time
import datetime
from typing import List, Tuple, Callable, Optional
from ..utils.constants import (
    ALLOWED_EXTENSIONS, 
    CHUNK_SIZE, 
    MAX_RETRIES, 
    VERIFY_TIMEOUT,
    VERIFY_POLL_INTERVAL
)
from ..utils.logger import setup_logger

logger = setup_logger("FileSystemHandler")

class FileSystemHandler:
    """
    Handles standard filesystem operations (local-to-local copy) and verification logic.
    """
    def __init__(self, status_callback: Optional[Callable] = None):
        self.status_callback = status_callback
        self.is_running = False
        self.copied_bytes = 0
        self.files_processed = 0
        self.failed_files: List[Tuple[str, str]] = []

    def update_status(self, text: str):
        """Status callback wrapper."""
        if self.status_callback:
            self.status_callback("status", text)
        logger.info(text)

    def update_progress(self, total_bytes: int, start_time: float):
        """Calculates percentage and ETA based on bytes copied."""
        if self.status_callback:
            if total_bytes > 0:
                percentage = self.copied_bytes / total_bytes
                self.status_callback("progress", percentage)
            
            # Calculate ETA
            elapsed_time = time.time() - start_time
            if elapsed_time > 0 and self.copied_bytes > 0:
                speed = self.copied_bytes / elapsed_time
                remaining_bytes = total_bytes - self.copied_bytes
                eta_seconds = remaining_bytes / speed
                eta_str = str(datetime.timedelta(seconds=int(eta_seconds)))
                self.status_callback("time", f"Estimated time remaining: {eta_str}")

    def backup_standard_mode(self, source: str, dest: str, total_bytes: int, start_time: float):
        """
        Executes a standard recursive file copy from source to destination.
        Reads all allowed files first, then chunks copy with progress.
        """
        self.is_running = True
        files_to_copy = []
        
        # Scan files
        for root, dirs, files in os.walk(source):
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in ALLOWED_EXTENSIONS:
                    full_path = os.path.join(root, file)
                    try:
                        size = os.path.getsize(full_path)
                        files_to_copy.append((full_path, size))
                    except: pass
        
        if not files_to_copy:
            self.update_status("No media files found (Standard Mode).")
            return

        for src_file, size in files_to_copy:
            if not self.is_running: break
            
            rel_path = os.path.relpath(src_file, source)
            dest_file = os.path.join(dest, rel_path)
            dest_dir = os.path.dirname(dest_file)
            
            self.update_status(f"Copying: {os.path.basename(src_file)}")
            
            try:
                os.makedirs(dest_dir, exist_ok=True)
                self.copy_file_chunked(src_file, dest_file)
                self.copied_bytes += size
                self.files_processed += 1
                self.update_progress(total_bytes, start_time)
            except Exception as e:
                logger.error(f"Failed: {src_file} - {e}")
                self.failed_files.append((os.path.basename(src_file), str(e)))

    def copy_file_chunked(self, src: str, dst: str):
        """
        Copies a single file in chunks to maintain UI responsiveness/progress updates.
        """
        total_size = os.path.getsize(src)
        copied = 0
        filename = os.path.basename(src)
        last_update_time = 0
        
        with open(src, 'rb') as fsrc:
            with open(dst, 'wb') as fdst:
                while True:
                    buf = fsrc.read(CHUNK_SIZE)
                    if not buf: break
                    fdst.write(buf)
                    copied += len(buf)
                    
                    # Throttle updates to ~10fps to save CPU/UI
                    current_time = time.time()
                    if self.status_callback and (current_time - last_update_time > 0.1 or copied == total_size):
                        self.status_callback("file_progress", (filename, copied, total_size))
                        last_update_time = current_time

    def stop(self):
        """Stops the copy operation."""
        self.is_running = False

    @staticmethod
    def verify_file_copy(path: str, expected_size: int, timeout: int = VERIFY_TIMEOUT, is_running_check: Optional[Callable[[], bool]] = None, progress_callback: Optional[Callable[[int, int], None]] = None) -> bool:
        """
        Verifies physically that the file has arrived at destination and size matches.
        Retry logic handles latency in MTP transfers or FS delays.
        """
        start = time.time()
        last_size = -1
        stable_count = 0
        
        logger.info(f"Verifying {os.path.basename(path)} (Expected: {expected_size} bytes)")
        
        actual_path = path
        
        while time.time() - start < timeout:
            if is_running_check and not is_running_check():
                return False
            
            # Check if file exists, or if a file with an extension exists
            if not os.path.exists(actual_path):
                dir_path = os.path.dirname(path)
                base_name = os.path.basename(path)
                
                if os.path.exists(dir_path):
                    try:
                        for f in os.listdir(dir_path):
                            if f.startswith(base_name) and f != base_name:
                                # Check if it's just an extension difference
                                if os.path.splitext(f)[0] == base_name:
                                    logger.debug(f"Found candidate with extension: {f}")
                                    actual_path = os.path.join(dir_path, f)
                                    break
                    except: pass

            if os.path.exists(actual_path):
                try:
                    current_size = os.path.getsize(actual_path)
                    
                    # Update progress
                    if progress_callback:
                        progress_callback(current_size, expected_size)
                    
                    if expected_size == 0 and current_size == 0:
                        if stable_count % 20 == 0:
                            logger.debug("File exists but is 0 bytes. Waiting for data...")
                        stable_count += 1
                        time.sleep(VERIFY_POLL_INTERVAL)
                        continue

                    if expected_size > 0 and current_size == expected_size:
                        if progress_callback: progress_callback(expected_size, expected_size)
                        return True
                    
                    if current_size > 0 and current_size == last_size:
                        stable_count += 1
                        if stable_count % 5 == 0:
                             logger.debug(f"Size stable at {current_size} (Expected {expected_size})... {stable_count}/5")
                    else:
                        stable_count = 0
                        if current_size != last_size:
                             logger.debug(f"Size changing: {last_size} -> {current_size}")
                    
                    last_size = current_size
                    
                    if stable_count >= 5:
                        logger.info(f"Accepted stable size {current_size} (Expected {expected_size}). Likely converted.")
                        if progress_callback: progress_callback(current_size, expected_size)
                        return True
                        
                except Exception as e:
                    logger.error(f"Error checking size: {e}")
            else:
                 if stable_count % 5 == 0:
                    logger.debug(f"File not found yet: {path}")
                 stable_count += 1
            
            time.sleep(VERIFY_POLL_INTERVAL)
            
        logger.error(f"Timeout waiting for {path}. Last size: {last_size}")
        return False
