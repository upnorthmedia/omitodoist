import os
import shutil
from pathlib import Path

def prepare_deployment():
    # Create necessary directories
    os.makedirs("templates", exist_ok=True)
    os.makedirs("static", exist_ok=True)
    
    # Ensure all required files exist
    required_files = [
        "main.py",
        "requirements.txt",
        "vercel.json",
        "templates/setup.html",
        "templates/setup_success.html"
    ]
    
    for file in required_files:
        if not os.path.exists(file):
            print(f"Error: Missing required file {file}")
            return False
    
    return True

if __name__ == "__main__":
    if prepare_deployment():
        print("Deployment preparation successful!")
    else:
        print("Deployment preparation failed!") 