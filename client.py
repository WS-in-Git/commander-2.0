import requests
import time
import socket
import os
import logging
import sys
import win32serviceutil
import win32service
import win32event
import servicemanager
import psutil
import win32api
import win32security

# --- WICHTIG: SERVER_URL ANPASSEN ---
# Ersetzen Sie '192.168.50.XXX' durch die tatsächliche IP-Adresse Ihres SERVER-RECHNERS!
SERVER_URL = "http://192.168.50.100:8000" # Passen Sie diese Zeile an!

# --- LOGGING-SETUP ---
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "client_log.txt")
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def get_local_ip():
    """Ermittelt die lokale IP-Adresse des Client-Rechners."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

CLIENT_IP_AS_ID = get_local_ip()

def register_client():
    """Meldet den Client beim Server an und sendet eine 'Ich lebe'-Nachricht."""
    try:
        response = requests.get(f"{SERVER_URL}/client_checkin/{CLIENT_IP_AS_ID}")
        if response.status_code == 200:
            logging.info(f"[{CLIENT_IP_AS_ID}] Erfolgreich beim Server eingecheckt.")
        else:
            logging.warning(f"[{CLIENT_IP_AS_ID}] Fehler beim Einchecken: {response.status_code} - {response.text}")
    except requests.exceptions.ConnectionError:
        logging.error(f"[{CLIENT_IP_AS_ID}] Verbindung zum Server ({SERVER_URL}) fehlgeschlagen. Versuche es erneut...")
    except Exception as e:
        logging.critical(f"[{CLIENT_IP_AS_ID}] Ein unerwarteter Fehler ist aufgetreten: {e}")

def is_process_running(process_name: str) -> bool:
    """Prüft, ob ein Prozess mit dem gegebenen Namen läuft."""
    # psutil.process_iter() iteriert über alle laufenden Prozesse
    for proc in psutil.process_iter(['name']):
        try:
            # Überprüft, ob der Prozessname (case-insensitive) übereinstimmt
            # Hier ist es wichtig, den exakten Prozessnamen zu verwenden, z.B. "3dsmax.exe"
            if proc.info['name'].lower() == process_name.lower(): # Exakte Übereinstimmung
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass # Ignoriert Prozesse, auf die nicht zugegriffen werden kann
    return False

def report_program_status(program_name: str, is_running: bool):
    """Sendet den Status eines Programms an den Server."""
    try:
        payload = {
            "client_ip": CLIENT_IP_AS_ID,
            "program_name": program_name,
            "is_running": is_running
        }
        response = requests.post(f"{SERVER_URL}/report_program_status", json=payload)
        if response.status_code == 200:
            logging.info(f"[{CLIENT_IP_AS_ID}] Status für '{program_name}' erfolgreich an Server gemeldet: {is_running}")
        else:
            logging.warning(f"[{CLIENT_IP_AS_ID}] Fehler beim Melden des Status für '{program_name}': {response.status_code} - {response.text}")
    except requests.exceptions.ConnectionError:
        logging.error(f"[{CLIENT_IP_AS_ID}] Verbindung zum Server ({SERVER_URL}) fehlgeschlagen beim Melden des Programstatus.")
    except Exception as e:
        logging.critical(f"[{CLIENT_IP_AS_ID}] Unerwarteter Fehler beim Melden des Programstatus: {e}")

def execute_command(command: str):
    """Führt einen vom Server erhaltenen Befehl aus."""
    logging.info(f"[{CLIENT_IP_AS_ID}] Befehl erhalten: '{command}'")
    
    if command == "reboot" or command == "shutdown":
        try:
            privilege = win32security.LookupPrivilegeValue(None, win32security.SE_SHUTDOWN_NAME)
            htoken = win32security.OpenProcessToken(win32api.GetCurrentProcess(), 
                                                   win32security.TOKEN_ADJUST_PRIVILEGES | win32security.TOKEN_QUERY)
            win32security.AdjustTokenPrivileges(htoken, 0, [(privilege, win32security.SE_PRIVILEGE_ENABLED)])
            
            if command == "reboot":
                logging.info(f"[{CLIENT_IP_AS_ID}] Führe Neustart über InitiateSystemShutdownEx aus...")
                win32api.InitiateSystemShutdownEx(
                    None, 
                    "Server requested reboot", 
                    0, 
                    True, 
                    True
                )
            else: # command == "shutdown"
                logging.info(f"[{CLIENT_IP_AS_ID}] Führe Herunterfahren über InitiateSystemShutdownEx aus...")
                win32api.InitiateSystemShutdownEx(
                    None, 
                    "Server requested shutdown", 
                    0, 
                    True, 
                    False
                )
            
            win32security.AdjustTokenPrivileges(htoken, 0, [(privilege, 0)])
            
        except Exception as e:
            logging.error(f"[{CLIENT_IP_AS_ID}] Fehler beim Ausführen von '{command}' über InitiateSystemShutdownEx: {e}")
            logging.warning(f"[{CLIENT_IP_AS_ID}] Versuche Fallback mit os.system für '{command}'...")
            os.system(f"shutdown /{ 'r' if command == 'reboot' else 's' } /t 1 /f")
    elif command.startswith("check_program:"):
        program_name = command.split(":")[1].strip()
        running = is_process_running(program_name)
        logging.info(f"[{CLIENT_IP_AS_ID}] Programm '{program_name}' läuft: {running}")
        report_program_status(program_name, running) # Melde den Status an den Server
    elif command == "test":
        logging.info(f"[{CLIENT_IP_AS_ID}] Testbefehl ausgeführt!")
        logging.info(f"[{CLIENT_IP_AS_ID}] Versuche Notepad zu starten...")
        os.system("notepad.exe")
    else:
        logging.warning(f"[{CLIENT_IP_AS_ID}] Unbekannter Befehl: {command}")

# --- Windows Service Klasse ---
class MyClientService(win32serviceutil.ServiceFramework):
    _svc_name_ = 'PythonClientService'
    _svc_display_name_ = 'Python Client Management Service'
    _svc_description_ = 'Verwaltet den Client-Rechner und kommuniziert mit dem Management-Server.'

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
        self.is_running = True

    def SvcStop(self):
        logging.info("Dienst wird gestoppt...")
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.hWaitStop)
        self.is_running = False

    def SvcDoRun(self):
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, '')
        )
        logging.info("Dienst gestartet. Beginne mit der Client-Kommunikation.")

        while self.is_running:
            register_client()
            try:
                response = requests.get(f"{SERVER_URL}/get_commands/{CLIENT_IP_AS_ID}")
                if response.status_code == 200:
                    commands_data = response.json()
                    if commands_data["commands"]:
                        for cmd in commands_data["commands"]:
                            execute_command(cmd)
                else:
                    logging.warning(f"[{CLIENT_IP_AS_ID}] Fehler beim Abrufen von Befehlen: {response.status_code} - {response.text}")
            except requests.exceptions.ConnectionError:
                logging.error(f"[{CLIENT_IP_AS_ID}] Verbindung zum Server ({SERVER_URL}) fehlgeschlagen beim Abrufen von Befehlen. Versuche es erneut...")
            except Exception as e:
                logging.critical(f"[{CLIENT_IP_AS_ID}] Ein unerwarteter Fehler beim Abrufen von Befehlen ist aufgetreten: {e}")

            if win32event.WaitForSingleObject(self.hWaitStop, 1 * 1000) == win32event.WAIT_OBJECT_0:
                break 

        logging.info("Dienst beendet.")

if __name__ == '__main__':
    if len(sys.argv) == 1:
        logging.info("Client-Skript direkt gestartet (nicht als Dienst).")
        print(f"Client gestartet mit temporärer ID (IP): {CLIENT_IP_AS_ID}")
        print(f"Verbinde zu Server: {SERVER_URL}")
        while True:
            register_client()
            try:
                response = requests.get(f"{SERVER_URL}/get_commands/{CLIENT_IP_AS_ID}")
                if response.status_code == 200:
                    commands_data = response.json()
                    if commands_data["commands"]:
                        for cmd in commands_data["commands"]:
                            execute_command(cmd)
            except requests.exceptions.ConnectionError:
                print(f"[{CLIENT_IP_AS_ID}] Verbindung zum Server ({SERVER_URL}) fehlgeschlagen beim Abrufen von Befehlen. Versuche es erneut...")
            except Exception as e:
                print(f"[{CLIENT_IP_AS_ID}] Ein unerwarteter Fehler beim Abrufen von Befehlen ist aufgetreten: {e}")
            time.sleep(10)
    else:
        try:
            win32serviceutil.HandleCommandLine(MyClientService)
        except win32service.error as e:
            logging.error(f"Fehler bei der Dienstverwaltung: {e}")
            print(f"Fehler bei der Dienstverwaltung: {e}")
            sys.exit(e.winerror)
