import subprocess, shlex, websocket, time, rel, sys, json, os

if len(sys.argv) <= 1:
    print("Usage: python3 control_services.py <PROCESS_NAME> [WEBSOCKET_ENDPOINT]")
    sys.exit(1)

PROCESS_NAME = sys.argv[1]
WEBSOCKET_ENDPOINT = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("SERVICE_CONTROLLER_WEBSOCKET_URL")
if not WEBSOCKET_ENDPOINT:
    print("Set SERVICE_CONTROLLER_WEBSOCKET_URL or pass the endpoint as the second argument")
    sys.exit(1)
print(WEBSOCKET_ENDPOINT)

# Define synchronous service control functions
def start_service(service_name):
    print("Starting service", service_name)
    subprocess.run(['sudo', 'systemctl', 'start', service_name], timeout=7)

def restart_service(service_name):
    print("Restarting service", service_name)
    subprocess.run(['sudo', 'systemctl', 'restart', service_name], timeout=7)

def stop_service(service_name):
    print("Stopping service", service_name)
    subprocess.run(['sudo', 'systemctl', 'stop', service_name], timeout=7)
    subprocess.run(['sudo', 'systemctl', 'clean', service_name], timeout=7)

async def handle_action(action, service):
    await HANDLERS[action](service)

def on_message(ws, message):
    print(message)
    try:
        message = message.replace("'", "\"")
        parsed = json.loads(message)
        action = parsed["action"]
        service = parsed["service"]
        
        if action in HANDLERS:
            print("Executing:", parsed)
            HANDLERS[action](service)
            print("Executed:", parsed)
    except Exception as e:
        print(f"Error when trying to process message: {e}")
        pass

def connected(ws):
    print("Connected to websocket")
    time.sleep(1)
    print("Sending process name:", PROCESS_NAME)
    ws.send(PROCESS_NAME)

# Map actions to async functions
HANDLERS = {
    "start": start_service,
    "restart": restart_service,
    "stop": stop_service
}

if __name__ == "__main__":
    ws = websocket.WebSocketApp(WEBSOCKET_ENDPOINT, on_message=on_message, on_open=connected)

    ws.run_forever(dispatcher=rel, reconnect=5)  # Set dispatcher to automatic reconnection, 5 second reconnect delay if connection closed unexpectedly
    rel.signal(2, rel.abort)  # Keyboard Interrupt
    rel.dispatch()
