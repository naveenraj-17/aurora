import os
import sys
import subprocess
import time
import platform
import shutil
import threading
import webbrowser

# ANSI colors
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
FRONTEND_DIR = os.path.join(ROOT_DIR, "frontend")

def print_step(msg):
    print(f"\n{Colors.BLUE}{Colors.BOLD}==> {msg}{Colors.ENDC}")

def print_success(msg):
    print(f"{Colors.GREEN}✓ {msg}{Colors.ENDC}")

def print_error(msg):
    print(f"{Colors.FAIL}✗ {msg}{Colors.ENDC}")

def check_command(command, helpful_msg=""):
    if shutil.which(command) is None:
        print_error(f"{command} not found. {helpful_msg}")
        return False
    return True

def install_backend():
    print_step("Setting up Backend...")
    
    venv_dir = os.path.join(BACKEND_DIR, "venv")
    if sys.platform == "win32":
        python_exe = os.path.join(venv_dir, "Scripts", "python.exe")
        pip_exe = os.path.join(venv_dir, "Scripts", "pip.exe")
    else:
        python_exe = os.path.join(venv_dir, "bin", "python")
        pip_exe = os.path.join(venv_dir, "bin", "pip")

    if not os.path.exists(venv_dir):
        print("Creating virtual environment...")
        subprocess.check_call([sys.executable, "-m", "venv", venv_dir])
    
    print("Installing requirements...")
    try:
        subprocess.check_call([pip_exe, "install", "-r", os.path.join(BACKEND_DIR, "requirements.txt")], 
                              stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        print_success("Backend dependencies installed.")
    except subprocess.CalledProcessError:
        print_error("Failed to install backend dependencies.")
        sys.exit(1)
        
    return python_exe

def install_frontend():
    print_step("Setting up Frontend...")
    
    if not check_command("npm", "Please install Node.js and npm."):
        sys.exit(1)
        
    print("Installing npm packages (this may take a while)...")
    try:
        # Use shell=True for Windows compatibility with npm
        shell_cmd = True if sys.platform == "win32" else False
        subprocess.check_call(["npm", "install"], cwd=FRONTEND_DIR, shell=shell_cmd,
                             stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        print_success("Frontend dependencies installed.")
    except subprocess.CalledProcessError:
        print_error("Failed to install frontend dependencies.")
        sys.exit(1)

def start_backend(python_exe):
    print_step("Starting Backend Server...")
    # Using Popen to run non-blocking
    return subprocess.Popen([python_exe, "main.py"], cwd=BACKEND_DIR)

def start_frontend():
    print_step("Starting Frontend Server...")
    shell_cmd = True if sys.platform == "win32" else False
    return subprocess.Popen(["npm", "run", "dev"], cwd=FRONTEND_DIR, shell=shell_cmd)

def open_browser():
    url = "http://localhost:3000"
    print_step(f"Opening {url}...")
    
    # Give servers a moment to start
    time.sleep(3)
    
    # Browsers to try for "app" mode
    browsers = ["google-chrome", "chromium", "brave-browser", "msedge"]
    if sys.platform == "darwin":
        browsers = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", 
                    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"]
    elif sys.platform == "win32":
        browsers = ["chrome.exe", "msedge.exe"]
    
    browser_cmd = None
    for b in browsers:
        if shutil.which(b):
            browser_cmd = b
            break
        # Check absolute paths for macOS
        if sys.platform == "darwin" and os.path.exists(b):
            browser_cmd = b
            break
            
    if browser_cmd:
        print(f"Opening in app mode using {browser_cmd}...")
        try:
            subprocess.Popen([browser_cmd, f"--app={url}"])
            return
        except Exception as e:
            print(f"Failed to open in app mode: {e}")
    
    # Fallback
    print("Opening in default browser...")
    webbrowser.open(url)

def main():
    print(f"{Colors.CYAN}=== Learn Agents Setup & Start ==={Colors.ENDC}")
    
    # 1. Checks
    if not check_command("node", "Please install Node.js."):
        sys.exit(1)
        
    # 2. Install
    python_exe = install_backend()
    install_frontend()
    
    # 3. Start
    backend_process = start_backend(python_exe)
    frontend_process = start_frontend()
    
    # 4. Browser
    threading.Thread(target=open_browser).start()
    
    print(f"\n{Colors.GREEN}{Colors.BOLD}Application is running!{Colors.ENDC}")
    print(f"{Colors.WARNING}Press Ctrl+C to stop servers and exit.{Colors.ENDC}\n")
    
    try:
        while True:
            time.sleep(1)
            # Check if processes are still alive
            if backend_process.poll() is not None:
                print_error("Backend crashed!")
                break
            # Note: Checking frontend npm process is trickier as it spawns children, 
            # but basic poll check helps if the main wrapper dies.
            if frontend_process.poll() is not None:
                print_error("Frontend crashed!")
                break
    except KeyboardInterrupt:
        print("\nStopping servers...")
        backend_process.terminate()
        # npm run dev spawns children, terminate() might not kill them all on Linux/Mac without groups
        # But for simple scripts this is usually "good enough" or requires pkill
        if sys.platform != "win32":
             # Try to kill the process group
             try:
                 os.killpg(os.getpgid(frontend_process.pid), 15)
             except:
                 frontend_process.terminate()
        else:
            frontend_process.terminate()
            
        print("Goodbye!")
        sys.exit(0)

if __name__ == "__main__":
    main()
