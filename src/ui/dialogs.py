import customtkinter
import tkinter as tk

class MultiSelectDialog(customtkinter.CTkToplevel):
    """
    A modal dialog that allows selecting multiple items from a list using checkboxes.
    """
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

class BackupModeDialog(customtkinter.CTkToplevel):
    """
    A modal dialog for choosing between 'Optimize' (HEIC conversion) and 'Keep Originals' modes.
    Returns a tuple: (convert_heic, skip_live_photos)
    """
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Choose Backup Mode")
        self.geometry("500x400")
        self.resizable(False, False)
        self.result = None # (convert_heic, skip_live_photos) or None
        
        # Center the window
        # self.eval(f'tk::PlaceWindow {str(self)} center') # Sometimes buggy in CTk
        
        self.lbl_title = customtkinter.CTkLabel(self, text="How would you like to transfer your files?", font=("Segoe UI", 18, "bold"))
        self.lbl_title.pack(pady=(20, 15))
        
        # Mode 1: Optimize
        self.frame_optimize = customtkinter.CTkFrame(self, fg_color="#E0A800" if customtkinter.get_appearance_mode()=="Light" else "#443300", corner_radius=10, border_color="#FFC107", border_width=2)
        self.frame_optimize.pack(padx=20, pady=10, fill="x")
        
        self.btn_optimize = customtkinter.CTkButton(
            self.frame_optimize, 
            text="Optimize for Windows", 
            command=self.on_optimize,
            font=("Segoe UI", 16, "bold"),
            fg_color="transparent",
            text_color="white",
            hover_color="#554400"
        )
        self.btn_optimize.pack(pady=(10, 5), padx=10, fill="x")
        
        self.lbl_opt_desc = customtkinter.CTkLabel(
            self.frame_optimize, 
            text="• Auto-convert HEIC photos to JPG\n• Skip 'Live Photo' videos to save space", 
            justify="left",
            text_color="#DDDDDD"
        )
        self.lbl_opt_desc.pack(pady=(0, 10), padx=20, anchor="w")

        # Mode 2: Keep Originals
        self.frame_original = customtkinter.CTkFrame(self, fg_color="transparent", corner_radius=10, border_color="gray", border_width=2)
        self.frame_original.pack(padx=20, pady=10, fill="x")
        
        self.btn_original = customtkinter.CTkButton(
            self.frame_original, 
            text="Keep Originals", 
            command=self.on_original,
            font=("Segoe UI", 16, "bold"),
            fg_color="transparent", 
            hover_color="#333333",
            text_color="#AAAAAA"
        )
        self.btn_original.pack(pady=(10, 5), padx=10, fill="x")
        
        self.lbl_orig_desc = customtkinter.CTkLabel(
            self.frame_original, 
            text="• Transfer files exactly as they are (Raw HEIC + MOV)\n• Best for full backup / future editing", 
            justify="left",
            text_color="gray"
        )
        self.lbl_orig_desc.pack(pady=(0, 10), padx=20, anchor="w")

        self.btn_cancel = customtkinter.CTkButton(self, text="Cancel", command=self.destroy, fg_color="transparent", text_color="gray", hover_color="#222222")
        self.btn_cancel.pack(pady=10)

        # Make modal
        self.transient(parent)
        self.grab_set()
        self.focus_set()
        self.wait_window()

    def on_optimize(self):
        # convert_heic=True, skip_live_photos=True
        self.result = (True, True)
        self.destroy()

    def on_original(self):
        # convert_heic=False, skip_live_photos=False
        self.result = (False, False)
        self.destroy()
