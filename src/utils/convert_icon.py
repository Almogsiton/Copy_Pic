from PIL import Image
import os

img_path = r"src/assets/app_icon.png"
ico_path = r"src/assets/app_icon.ico"

try:
    img = Image.open(img_path)
    # Save as ICO with multiple sizes for best scaling behavior
    img.save(ico_path, format='ICO', sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    print(f"Successfully created {ico_path}")
except Exception as e:
    print(f"Error: {e}")
