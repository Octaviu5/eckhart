import socket
import json
import os
import dbus
import time
import argparse

# --- CONFIG ---
UID = os.getuid()
SOCKET_PATH = f"/tmp/eckhart/{UID}.sock"
NOTIF_TIMEOUT = 6000 
APP_NAME = "EckhartUI"

# Notification triggers
TRIGGER_EVENTS = ["INTENTION", "TRACKING", "KILLED", "DENIED", "EXIT", "CHILL", "GRACE"]
# Time Milestones in seconds
MILESTONES = {900: "15m", 600: "10m", 300: "5m", 180: "3m", 60: "1m", 10: "10s", 9: "9s", 8: "8s", 7: "7s", 6: "6s", 5: "5s", 4: "4s", 3: "3s", 2: "2s", 1: "1s", }

# --- CLI ARGS ---
parser = argparse.ArgumentParser()
parser.add_argument("-v", "--verbose", action="store_true", help="Show logic in terminal")
args = parser.parse_args()

# --- DBUS SETUP ---
bus = dbus.SessionBus()
notif_obj = bus.get_object("org.freedesktop.Notifications", "/org/freedesktop/Notifications")
notify_interface = dbus.Interface(notif_obj, "org.freedesktop.Notifications")

last_notif_id = 999
current_state = {} 
milestone_memory = {} # Tracks {block_name: last_known_remaining_time}

def log_msg(status, event, aaa, bbb, state=None):
    if args.verbose:
        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] EVENT: {str(event):<12} | STATUS: {str(status):<12} | AAA: {str(aaa):<15} | BBB: {str(bbb)} \n{state}\n" )

def show_hud(summary):
    global last_notif_id
    if args.verbose:
        print(f"-> UI PUSH:\n{summary}\n\n")

    last_notif_id = notify_interface.Notify(
        APP_NAME, last_notif_id, "", summary, "", [], {"urgency": 1}, NOTIF_TIMEOUT
    )

def notify(summary, id):
    if args.verbose:
        print(f"-> UI PUSH:\n{summary}\n\n")
    notify_interface.Notify(
        APP_NAME, id, "", summary, "", [], {"urgency": 1}, NOTIF_TIMEOUT
    ) 


def format_time(seconds):
    if seconds >= 900000: return "∞"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}h {m}m" if h > 0 else f"{m}m {s}s"

def time_to_seconds(t_str):
    h, m = map(int, t_str.split(":"))
    return h * 3600 + m * 60

def get_seconds_since_midnight():
    now = time.localtime()
    return now.tm_hour * 3600 + now.tm_min * 60 + now.tm_sec

def format_binaries(binary_list):
    if not binary_list: 
        return ""
    unique_bins = sorted(set(binary_list))
    return "\n".join(f" - {os.path.basename(bin)}" for bin in unique_bins)

previous_sec_was_chill = False

def parse_state():
    global current_state, milestone_memory, previous_sec_was_chill
    my_state = current_state.get(str(UID))
    
    if not my_state: return "NO INTENTION FOUND", False

    # --- 1. Extract Data ---
    intent_name = my_state.get("st_intention_name")
    intent_bins = my_state.get("st_intention_binaries", []) 
    chill_remaining = my_state.get("st_chill_remaining", 0)
    grace_remaining = my_state.get("st_grace_remaining", 0)
    pending_remaining = my_state.get("st_pending_remaining", 0)
    pending_name = my_state.get("st_pending_name", 0)        
    lines = []
    blocks = my_state.get("st_time_blocks", {})
    now_sec = get_seconds_since_midnight()
    any_milestone_hit = False

    # --- 2. INTENTION SUMMARY Generation ---
    for name, info in blocks.items():
        # In the new arch, only the active intention has running binaries
        is_active = (name == intent_name)
        running_bins = intent_bins if is_active else []
        
        time_budget = info.get("st_time_budget", 999999)
        used_budget = info.get("st_used_budget", 0)
        window_rem = float("inf")
        active_end_str = "END" 
        
        for w in info.get("st_time_windows", []):
            try:
                start_str, end_str = w.split("-")
                start, end = map(time_to_seconds, [start_str, end_str])
                if start <= now_sec <= end:
                    window_rem = end - now_sec
                    active_end_str = end_str 
                    break
            except: continue

        rem_time = max(0, min((time_budget - used_budget), window_rem))

        # --- MILESTONE LOGIC ---
        if is_active:
            last_val = milestone_memory.get(name, 999999)
            for m_sec in sorted(MILESTONES.keys(), reverse=True):
                if last_val > m_sec >= rem_time:
                    any_milestone_hit = True
                    break
            milestone_memory[name] = rem_time

            reason = "W/B" if abs((time_budget - used_budget) - window_rem) < 5 else ("W" if window_rem < (time_budget - used_budget) else "B")
            
            if time_budget >= 99999:
                display_time = f"> {active_end_str}"
            else:
                display_time = f"({format_time(rem_time)})({reason}) > {active_end_str}"


            if not any_milestone_hit:
                lines.append(f"🎯 {name.upper()}{display_time}\n{format_binaries(running_bins)}")

            else:
                lines = f"⚠️ {name.upper()} WILL END IN {format_time(rem_time)} ⚠️"

    if grace_remaining > 0:
        expiry_ts = time.time() + grace_remaining
        return f"🧸 GRACE: {format_time(grace_remaining)}", False, grace_remaining

    elif pending_remaining > 0:
        expiry_ts = time.time() + pending_remaining
        return f"⏲️ LOCKING INTENTION TO {pending_name} {format_time(pending_remaining)}", False, True

    elif chill_remaining > 0:
        expiry_ts = time.time() + chill_remaining
        return f"🍦 CHILLDOWN: {format_time(chill_remaining)}", False, chill_remaining
    else:
        if intent_name:
            return f"".join(lines), any_milestone_hit, False
        else:      
            return f"🎯 NO INTENTION SET", False, False
                
            
def main():
    global current_state
    if args.verbose: print(f"Eckhart UI Active-Filter - UID {UID}")

    last_heartbeat = time.time()
    last_warning_time = 0
    daemon_was_alive = False

    while True:
        # Check if the socket file even exists
        if not os.path.exists(SOCKET_PATH):
            now = time.time()
            if now - last_warning_time > 5:
                notify("💀 ROOT DAEMON DOWN: Socket missing!", 0)
                last_warning_time = now
            daemon_was_alive = False
            time.sleep(2)
            continue
            
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                # Set a timeout so recv() doesn't block forever if the daemon hangs
                client.settimeout(2.0)
                client.connect(SOCKET_PATH)
                
                # The "Scream like a bitch" moment
                notify("⚡ ECKHART ONLINE: Root is now enforcing.", 0)
                if args.verbose: print("Connected to Root Daemon.")
                
                last_heartbeat = time.time()
                daemon_was_alive = True
                buffer = ""

                while True:
                    try:
                        data = client.recv(4096).decode()
                        if not data: 
                            if args.verbose: print("Connection closed by daemon.")
                            break
                        
                        buffer += data
                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            try:
                                msg = json.loads(line)
                                # Any valid message resets the heartbeat
                                last_heartbeat = time.time()
                                
                                status = msg.get("status")
                                event = msg.get("event")

                                if "state" in msg and msg["state"]:
                                    current_state[str(UID)] = msg["state"]

                                # Handle standard status pulses
                                if status == "STATUS":
                                    summary, hit, chill_remaining = parse_state()
                                    if hit or chill_remaining:
                                        show_hud(summary)

                                # Handle specific event triggers
                                if event == "WINE":
                                    notify(f"🍷-{status}: {msg.get('aaa')}", 0)

                                if event == "DENIED":
                                    t = f"🚫 DENIED-{status}: {os.path.basename(msg.get('bbb', 'unknown'))}"
                                    notify(t, 0)

                                if event == "INTENTION":
                                    if status == "RELEASED":
                                        notify(f"✅ INTENTION RELEASED: {msg.get('bbb')}", 0)

                                if event in TRIGGER_EVENTS:
                                    log_msg(status, event, msg.get("aaa"), msg.get("bbb"), msg.get("state"))
                                    summary, _, _ = parse_state()
                                    if summary:
                                        show_hud(summary)

                            except json.JSONDecodeError:
                                continue

                    except socket.timeout:
                        # We haven't received data in 2 seconds. 
                        # Check if the total silence exceeds our 5-second limit.
                        now = time.time()
                        if now - last_heartbeat > 5:
                            if now - last_warning_time > 5:
                                notify("⚠️ DAEMON UNRESPONSIVE: Heartbeat lost!", 0)
                                last_warning_time = now
                        continue 

        except (ConnectionRefusedError, socket.error) as e:
            now = time.time()
            if now - last_warning_time > 5:
                # Only scream if we were previously alive or if it's been a while
                msg = "🛑 ROOT DAEMON DOWN: Connection Refused" if not daemon_was_alive else "💀 DAEMON CRASHED: Connection Lost"
                notify(msg, 0)
                last_warning_time = now
            
            # Wipe state so the UI doesn't show old garbage
            current_state[str(UID)] = {}
            daemon_was_alive = False
            time.sleep(2)

        except Exception as e:
            if args.verbose: print(f"Unexpected Error: {e}")
            time.sleep(2)

if __name__ == "__main__":
    main()
