from fastapi import FastAPI
from wakeonlan import send_magic_packet
import random
import configparser
from typing import Dict, List
from pydantic import BaseModel
import logging # Neu: Für die Protokollierung
import os      # Neu: Für Pfadoperationen

app = FastAPI()

# --- LOGGING-SETUP FÜR DEN SERVER ---
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server_log.txt")
# Konfiguriere den Root-Logger, der auch die Uvicorn-Logs erfasst
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO, # Logge INFO-Meldungen und höher
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
# Optional: Wenn du die Logs auch in der Konsole sehen möchtest, füge einen StreamHandler hinzu
# console_handler = logging.StreamHandler()
# console_handler.setLevel(logging.INFO)
# console_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
# logging.getLogger().addHandler(console_handler)

# Hier speichern wir Befehle, die auf die Clients warten.
client_pending_commands: Dict[str, List[str]] = {}

# Eine globale Variable, um den Status der Programme pro Client zu speichern
client_program_statuses: Dict[str, Dict[str, bool]] = {}


# Funktion zum Laden der Client-Daten aus der INI-Datei
def load_clients_from_ini():
    config = configparser.ConfigParser()
    try:
        config.read('clients.ini')
        logging.info("clients.ini erfolgreich geladen.")
    except Exception as e:
        logging.error(f"Fehler beim Lesen der clients.ini: {e}")
        return []

    loaded_clients = []
    for i, section in enumerate(config.sections()):
        client_data = config[section]
        client = {
            "id": i + 1,
            "ip": section,
            "name": client_data.get("Name", f"Unbekannt_{i+1}"),
            "user": client_data.get("User", "Unbekannt"),
            "mac": client_data.get("MAC", "").replace(":", "").replace("-", "").upper(),
            "cluster": int(client_data.get("Cluster", 0))
        }
        loaded_clients.append(client)
    logging.info(f"{len(loaded_clients)} Clients aus clients.ini geladen.")
    return loaded_clients

# Lade die Clients beim Start des Servers
clients = load_clients_from_ini()

# Definiere die Konstanten für Cluster
CLUSTER_ARBEITSRECHNER = 20
MAX_CLUSTER_NUMBER = 19

# Dieser Endpunkt gibt die Liste der Clients zurück.
@app.get("/clients")
def get_clients():
    for client in clients:
        if "status" not in client:
             if random.random() > 0.5:
                 client["status"] = "online"
             else:
                 client["status"] = "offline"
        
        client["running_programs"] = client_program_statuses.get(client["ip"], {})
    
    logging.info("Client-Liste angefragt.")
    return clients

# Dieser neue Endpunkt weckt einen Rechner auf.
@app.get("/wakeup/{client_id}")
def wakeup_client(client_id: int):
    client = next((c for c in clients if c["id"] == client_id), None)
    
    if client:
        send_magic_packet(client["mac"])
        
        message = f"Wake-on-LAN Paket an {client['name']} ({client['mac']}) gesendet."
        logging.info(message)
        return {"status": "success", "message": message, "client": client}
    else:
        message = f"Client mit ID {client_id} nicht gefunden."
        logging.warning(message)
        return {"status": "error", "message": message}

# Dieser Endpunkt akzeptiert einen Befehl und die ID eines Clients.
# Der Befehl wird für den Client gespeichert.
@app.get("/command/{client_id}/{command}")
def send_command(client_id: int, command: str):
    client = next((c for c in clients if c["id"] == client_id), None)
    
    if client:
        client_ip = client["ip"]
        if client_ip not in client_pending_commands:
            client_pending_commands[client_ip] = []
        
        client_pending_commands[client_ip].append(command)
        
        message = f"Befehl '{command}' für {client['name']} ({client_ip}) gespeichert."
        logging.info(message)
        return {"status": "success", "message": message, "client": client}
    else:
        message = f"Client mit ID {client_id} nicht gefunden."
        logging.warning(message)
        return {"status": "error", "message": message}

# Dieser Endpunkt wird vom Client aufgerufen, um seine wartenden Befehle abzurufen.
@app.get("/get_commands/{client_ip}")
def get_commands_for_client(client_ip: str):
    commands_for_this_client = client_pending_commands.get(client_ip, [])
    
    if commands_for_this_client:
        logging.info(f"Befehle für Client {client_ip} abgerufen: {commands_for_this_client}")
        client_pending_commands[client_ip] = []
    
    return {"status": "success", "commands": commands_for_this_client}

# Definition eines Datenmodells für die vom Client gesendeten Informationen
class ProgramStatusReport(BaseModel):
    client_ip: str
    program_name: str
    is_running: bool

# Dieser Endpunkt empfängt den Programstatus von einem Client.
@app.post("/report_program_status")
def report_program_status_from_client(report: ProgramStatusReport):
    client_ip = report.client_ip
    program_name = report.program_name
    is_running = report.is_running

    if client_ip not in client_program_statuses:
        client_program_statuses[client_ip] = {}
    
    client_program_statuses[client_ip][program_name] = is_running
    
    logging.info(f"Status für '{program_name}' auf Client {client_ip} gemeldet: {is_running}")
    return {"status": "success", "message": "Program status received"}


# Der "Hallo Welt"-Endpunkt.
@app.get("/")
def read_root():
    logging.info("Hallo Welt Endpunkt angefragt.")
    return {"message": "Hallo Welt"}

# Dieser Endpunkt empfängt eine "Check-in"-Nachricht vom Client.
@app.get("/client_checkin/{client_ip}")
def client_checkin(client_ip: str):
    client_found = next((c for c in clients if c["ip"] == client_ip), None)
    
    if client_found:
        client_found["status"] = "online"
        logging.info(f"Client {client_ip} ({client_found['name']}) hat sich eingecheckt.")
        return {"status": "success", "message": f"Client {client_ip} eingecheckt", "client": client_found}
    else:
        logging.warning(f"Unbekannter Client {client_ip} hat sich eingecheckt.")
        return {"status": "error", "message": f"Client {client_ip} nicht in Liste gefunden"}

# Optional: Endpunkt, um Clients nach Cluster zu filtern
@app.get("/clients/cluster/{cluster_id}")
def get_clients_by_cluster(cluster_id: int):
    filtered_clients = [c for c in clients if c["cluster"] == cluster_id]
    for client in filtered_clients:
        if "status" not in client:
             if random.random() > 0.5:
                 client["status"] = "online"
             else:
                 client["status"] = "offline"
        client["running_programs"] = client_program_statuses.get(client["ip"], {})
    logging.info(f"Clients für Cluster {cluster_id} angefragt.")
    return filtered_clients

# Optional: Endpunkt, um alle Cluster anzuzeigen
@app.get("/clusters")
def get_clusters():
    unique_clusters = sorted(list(set(c["cluster"] for c in clients)))
    logging.info("Alle Cluster angefragt.")
    return {"clusters": unique_clusters}


