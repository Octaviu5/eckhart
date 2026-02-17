from bcc import BPF
import os
import time
import signal
import subprocess
import socket
import json
import argparse
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RULES_PATH = os.path.join(SCRIPT_DIR, "rules.json")
STATE_PATH = os.path.join(SCRIPT_DIR, "state.json")

def load_profiles():
    try:
        with open(RULES_PATH, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading rules: {e}")
        return {}

# --- EBPF SETUP ---
ebpf_code = """
#include <uapi/linux/ptrace.h>
#include <linux/sched.h>

struct data_t {
    u32 pid;
    u32 uid;
    char comm[16];
    char filename[256];
    char args[128]; // Store a snippet of the arguments
};

BPF_PERF_OUTPUT(events);

TRACEPOINT_PROBE(syscalls, sys_enter_execve) {
    struct data_t data = {};
    data.uid = bpf_get_current_uid_gid() & 0xFFFFFFFF;
    data.pid = bpf_get_current_pid_tgid() >> 32;
    bpf_get_current_comm(&data.comm, sizeof(data.comm));
    
    // Read the binary path
    bpf_probe_read_user_str(&data.filename, sizeof(data.filename), args->filename);
    
    // Read the first argument (usually the most important one for scripts)
    const char **argv = (const char **)args->argv;
    const char *argp;
    
    bpf_probe_read_user(&argp, sizeof(argp), &argv[1]);
    if (argp) {
        bpf_probe_read_user_str(&data.args, sizeof(data.args), argp);
    }

    events.perf_submit(args, &data, sizeof(data));
    return 0;
}
"""

def get_seconds_since_midnight():
    now = datetime.now()
    return now.hour * 3600 + now.minute * 60 + now.second

def time_to_seconds(t_str):
    h, m = map(int, t_str.split(":"))
    return h * 3600 + m * 60

def is_in_window(seconds, windows):
    if not windows: return True
    for w in windows:
        start_str, end_str = w.split("-")
        if time_to_seconds(start_str) <= seconds <= time_to_seconds(end_str):
            return True
    return False

def get_day_key():
    return datetime.now().strftime("%a").lower()

def load_persistence():
    today = datetime.now().strftime("%Y-%m-%d")
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, "r") as f:
                data = json.load(f)
                if data.get("date") == today:
                    return data.get("used-budget", {})
        except: pass
    return {}

# --- INITIALIZE STATE ---
saved_data = load_persistence()
last_saved_snapshot = {} 
last_save_tick = time.time()

USER_PROFILES = load_profiles()
USER_STATES = {}
SOCKET_BASE_DIR = "/tmp/eckhart"
ACTIVE_SOCKETS = {}

# --- ENFORCEMENT CONFIG ---
COMMITMENT_WINDOW = 15.0  # Seconds to lock an intention
WALL_TICK_RATE = 1.0     # Frequency of status pulses
SAVE_INTERVAL = 30.0     # Persistence save frequency
SUSSY_CHECK_RATE = 2.0   # How often to audit dev zones
GRACE_PERIOD = 10.0
CHILL_DURATION = 180.0
def main():
    parser = argparse.ArgumentParser(description="Eckhart Daemon Enforcer")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable console logging")
    args = parser.parse_args()
    VERBOSE = args.verbose
    LOG_UNTRACKED = False

    global last_saved_snapshot
    global last_save_tick
    global USER_STATES

    if os.geteuid() != 0:
        print("Root only. Use sudo.")
        return
    # --- STARTUP BANNER ---    
    print("\033[95m" + "═" * 60 + "\033[0m")
    print("\033[95m[+] ECKHART v1.0 | STAY PRESENT.\033[0m")
    mode_str = "ENABLED." if VERBOSE else "DISABLED."
    print(f"\033[93m[+] VERBOSE: {mode_str}\033[0m")
    mode_str = "ENABLED." if LOG_UNTRACKED else "DISABLED."
    print(f"\033[93m[+] LOG_UNTRACKED: {mode_str}\033[0m")    
    print("\033[95m" + "═" * 60 + "\033[0m")

    if os.path.exists(SOCKET_BASE_DIR):
        import shutil
        shutil.rmtree(SOCKET_BASE_DIR)
    os.makedirs(SOCKET_BASE_DIR, mode=0o755)

    for u_id in USER_PROFILES.keys():
        user_history = saved_data.get(str(u_id), {})
        USER_STATES[u_id] = {
            "active_intention": {"name": None, "pids": {}}, 
            "pending_intention": {"name": None, "since": 0}, # <--- NEW
            "intentions": {
                name: user_history.get(name, 0)
                for name in USER_PROFILES[u_id]["intentions"].keys()
            },
            "sussy_binaries": {},
            "chilldown_until": 0,
            "grace_until": 0,
            "conn": None
        }

        s_path = os.path.join(SOCKET_BASE_DIR, f"{u_id}.sock")
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.setblocking(False)
        s.bind(s_path)
        s.listen(1)
        os.chmod(s_path, 0o666)
        ACTIVE_SOCKETS[u_id] = s


    def send_to_socket(target_uid_str, event_uid, event, status, aaa, bbb, now):
        state = USER_STATES[target_uid_str]
        
        # --- CONNECTION HANDLING ---
        if state["conn"] is None:
            try:
                conn, _ = ACTIVE_SOCKETS[target_uid_str].accept()
                conn.setblocking(False)
                state["conn"] = conn
                
                welcome = {
                    "ts": int(now), "uid": 0, "event": "SYSTEM", "status": "ONLINE",
                    "aaa": "DAEMON_ACTIVE", "bbb": "Eckhart monitoring started.",
                    "state": None 
                }
                state["conn"].sendall((json.dumps(welcome) + "\n").encode())
            except (BlockingIOError, InterruptedError): 
                return

        profile = USER_PROFILES[target_uid_str]
        active_blocks = {}
        
        current_intent_name = state["active_intention"]["name"]
        pending = state["pending_intention"]
        running_intent_binaries = list(set(state["active_intention"]["pids"].values()))

        # --- CALCULATE PENDING REMAINING ---
        pending_remaining = 0
        if pending["name"]:
            # Hardcoded 15s window from your main loop logic
            elapsed = now - pending["since"]
            pending_remaining = max(0, int(15 - elapsed))

        for name, config in profile["intentions"].items():
            used_budget = state["intentions"].get(name, 0)
            day_rule = config["days"].get(get_day_key(), config["days"].get("def"))
            budget, windows = (day_rule.get("time-budget", 999999), day_rule.get("time-windows", [])) if day_rule else (0, [])

            active_blocks[name] = {
                "st_time_windows": windows,
                "st_time_budget": budget,
                "st_used_budget": used_budget,
            }

        try:
            msg = {
                "ts": int(now), 
                "uid": event_uid, 
                "event": event, 
                "status": status, 
                "aaa": aaa, 
                "bbb": bbb,
                "state": {
                    "st_intention_name": current_intent_name,
                    "st_intention_binaries": running_intent_binaries,
                    "st_pending_name": pending["name"],
                    "st_pending_remaining": pending_remaining, # Here is your number, imbecil
                    "st_chill_remaining": max(0, int(1 + state["chilldown_until"] - now )),
                    "st_grace_remaining": max(0, int(state["grace_until"] - now)) if state["grace_until"] > 0 else 0,
                    "st_time_blocks": active_blocks
                }
            }
            state["conn"].sendall((json.dumps(msg) + "\n").encode())
        except Exception:
            try: state["conn"].close()
            except: pass
            state["conn"] = None


    def log(uid, event, status, aaa, bbb):
        now = time.time()
        str_uid = str(uid)
        if VERBOSE and status != "STATUS":
            readable_time = datetime.fromtimestamp(now).strftime("%H:%M:%S")
            print(f"[{readable_time}] {str_uid:<6} | {event:<12} | {status:<12} | {aaa:<10} | {bbb}")

        if uid == 0:
            for t_uid in USER_STATES.keys(): send_to_socket(t_uid, uid, event, status, aaa, bbb, now)
        elif str_uid in USER_STATES:
            send_to_socket(str_uid, uid, event, status, aaa, bbb, now)

    def save_persistence(force=False):
        global last_saved_snapshot, last_save_tick
        today = datetime.now().strftime("%Y-%m-%d")
        current_budgets = json.loads(json.dumps({str(u): state["intentions"] for u, state in USER_STATES.items()}))
        
        if not force and current_budgets == last_saved_snapshot: 
            return 
            
        try:
            with open(STATE_PATH, "w") as f:
                json.dump({"date": today, "used-budget": current_budgets}, f)
            last_saved_snapshot = current_budgets
            last_save_tick = time.time() 
            log(0, "SYSTEM", "DISK", "", "OK")
        except Exception as e: 
            log(0, "SYSTEM", "DISK_ERR", "", str(e))

    def get_real_path(pid, raw_path):
        if raw_path.startswith("/"): return os.path.realpath(raw_path)
        try:
            cwd = os.readlink(f"/proc/{pid}/cwd")
            return os.path.realpath(os.path.join(cwd, raw_path))
        except: return os.path.realpath(raw_path)

    def is_gui_process(pid):
        try:
            with open(f"/proc/{pid}/maps", "r") as f:
                for line in f:
                    if any(x in line for x in ["libgtk", "libQt", "libX11", "libwayland"]): return True
        except: pass
        return False

    def enforce_rules(pid, uid, full_path, extra_args):
        if not os.path.exists(full_path) and " (deleted)" not in full_path: return
        str_uid = str(uid)
        if str_uid not in USER_PROFILES or uid == 0 or pid <= 1: return

        profile = USER_PROFILES[str_uid]
        state = USER_STATES[str_uid]
        normalized_path = full_path.replace(" (deleted)", "")
        binary_name = os.path.basename(normalized_path)

        is_authorized = any(normalized_path.startswith(z) for z in profile["authorized_zones"])
        is_dev_zone = any(normalized_path.startswith(z) for z in profile["dev_zones"])

        if is_authorized:
            # --- DAYS OFF CHECK ---            
            days_off_config = profile.get("days_off", {})
            today_off_list = days_off_config.get(get_day_key(), days_off_config.get("def", []))

            if binary_name in today_off_list:
                try: os.kill(pid, signal.SIGKILL)
                except: pass
                log(uid, "DENIED", "BIN_DAY", pid, normalized_path)
                return

            intent_name, intent_config = None, None
            for name, config in profile["intentions"].items():
                if binary_name in config["binaries"]:
                    intent_name, intent_config = name, config
                    break

            if not intent_name:
                if LOG_UNTRACKED:
                    log(uid, "UNTRACKED", "", pid, normalized_path)
                return

            # --- ENFORCEMENT ---
            now = time.time()
            # GATE 1: Chilldown
            if state["chilldown_until"] > now:
                try: os.kill(pid, signal.SIGKILL)
                except: pass
                log(uid, "DENIED", "CHILL", pid, normalized_path)
                return

            # --- CONFLICT GATE (Locked or Pending) ---
            active_name = state["active_intention"]["name"]
            pending_name = state["pending_intention"]["name"]
            
            if (active_name and intent_name != active_name) or \
               (pending_name and intent_name != pending_name):
                try: os.kill(pid, signal.SIGKILL)
                except: pass
                log(uid, "DENIED", "CONFLICT", pid, normalized_path)
                return

            day_rule = intent_config["days"].get(get_day_key(), intent_config["days"].get("def"))
            if not day_rule:
                try: os.kill(pid, signal.SIGKILL)
                except: pass
                log(uid, "DENIED", "DAY", pid, normalized_path)
                return

            if not is_in_window(get_seconds_since_midnight(), day_rule.get("time-windows", [])):
                try: os.kill(pid, signal.SIGKILL)
                except: pass
                log(uid, "DENIED", "WINDOW", pid, normalized_path)
                return

            used = state["intentions"].get(intent_name, 0)
            if used >= day_rule.get("time-budget", float("inf")):
                try: os.kill(pid, signal.SIGKILL)
                except: pass
                log(uid, "DENIED", "BUDGET", pid, normalized_path)
                return
                
            # GATE 4: SINGLE?
            if intent_config.get("single") == "true":
                running_pids = state["active_intention"]["pids"]
                if running_pids:
                    current_running_binaries = set(os.path.basename(path) for path in running_pids.values())
                    if any(b_name != binary_name for b_name in current_running_binaries):
                        try: os.kill(pid, signal.SIGKILL)
                        except: pass
                        log(uid, "DENIED", "SINGLE", pid, normalized_path)
                        return

            # --- SUCCESS: TRACK ---
            if active_name is None and pending_name is None:
                state["pending_intention"]["name"] = intent_name
                state["pending_intention"]["since"] = now
                log(uid, "INTENTION", "RESERVED", "", f"{intent_name.upper()}")
            
            elif active_name == intent_name and state["grace_until"] > 0:
                state["grace_until"] = 0
                log(uid, "INTENTION", "RESTORED", "", intent_name.upper())

            if pid not in state["active_intention"]["pids"]:
                state["active_intention"]["pids"][pid] = normalized_path
                log(uid, "TRACKING", "", pid, normalized_path)
                if binary_name in profile["hooks"]:
                    try: subprocess.Popen(["python3", profile["hooks"][binary_name], str(pid), str(uid)])
                    except: pass

        elif is_dev_zone:
            if state["chilldown_until"] > time.time() or is_gui_process(pid):
                try: os.kill(pid, signal.SIGKILL)
                except: pass
                log(uid, "DENIED", "DEV-CHILL", pid, normalized_path)
            else:
                if pid not in state["sussy_binaries"]:
                    log(uid, "TRACKING", "SUSSY", pid, full_path)
                    state["sussy_binaries"][pid] = {"uid": uid, "path": normalized_path}
        else:
            try: os.kill(pid, signal.SIGKILL)
            except: pass
            log(uid, "DENIED", "PATH", pid, normalized_path)

    def handle_launch(cpu, data, size):
        event = b["events"].event(data)
        try:
            raw_path = event.filename.decode()
            extra_args = event.args.decode(errors='ignore')
            full_path = get_real_path(event.pid, raw_path)
            enforce_rules(event.pid, event.uid, full_path, extra_args)
        except: pass

    def run_startup_sweep():
        log(0, "SYSTEM", "AUDIT", "", "START")
        with os.scandir("/proc") as it:
            for entry in it:
                if not entry.name.isdigit(): continue
                pid = int(entry.name)
                if pid == os.getpid() or pid == 1: continue
                try:
                    uid = entry.stat().st_uid
                    full_path = os.readlink(f"/proc/{pid}/exe")
                    enforce_rules(pid, uid, full_path, "")
                except: continue
        log(0, "SYSTEM", "AUDIT", "", "FINISH")
    
    # --- STARTUP ---
    b = BPF(text=ebpf_code)
    b["events"].open_perf_buffer(handle_launch)
    run_startup_sweep()
    
    last_wall_tick = time.time()
    last_sussy_tick = 0 
    last_heartbeat = time.time()

    try:
        while True:
            now = time.time()
            if now - last_heartbeat > 5.0:
                log(0, "SYSTEM", "WAKE", "", "REINIT")
                b.cleanup()
                b = BPF(text=ebpf_code)
                b["events"].open_perf_buffer(handle_launch)
                run_startup_sweep()
            last_heartbeat = now

            b.perf_buffer_poll(timeout=10)
            last_heartbeat = now 

            for u_id, state in USER_STATES.items():
                profile = USER_PROFILES[u_id]

                if state["chilldown_until"] > 0 and now >= state["chilldown_until"]:
                    state["chilldown_until"] = 0
                    log(u_id, "CHILL", "EXPIRED", "", "OK")                

                active_intent = state["active_intention"]["name"]
                pending = state["pending_intention"]

                # 1. PENDING COMMITMENT
                if pending["name"] and active_intent is None:
                    if now - pending["since"] >= COMMITMENT_WINDOW:
                        state["active_intention"]["name"] = pending["name"]
                        active_intent = pending["name"] # update local ref
                        pending["name"] = None
                        pending["since"] = 0
                        log(u_id, "INTENTION", "LOCKED", "", active_intent.upper())

                # 3. BAIL OUT (Pending)
                if not state["active_intention"]["pids"] and active_intent is None and pending["name"]:
                    pending["name"] = None
                    pending["since"] = 0
                    log(u_id, "INTENTION", "CANCELLED", "", "")


                # 4. GRACE/CHILL (Active)
                elif active_intent and not state["active_intention"]["pids"]:
                    config = profile["intentions"][active_intent]
                    day_rule = config["days"].get(get_day_key(), config["days"].get("def"))
                    now_sec = get_seconds_since_midnight()
                    
                    # Check if we still have budget/window
                    has_budget = state["intentions"][active_intent] < day_rule.get("time-budget", float("inf"))
                    in_window = is_in_window(now_sec, day_rule.get("time-windows", []))

                    if has_budget and in_window:
                        if state["grace_until"] == 0:
                            # Use the new global GRACE_PERIOD var here
                            state["grace_until"] = now + GRACE_PERIOD
                            log(u_id, "GRACE", "PENDING", "", f"{active_intent.upper()}")
                        elif now >= state["grace_until"]:
                            state["active_intention"]["name"] = None
                            state["grace_until"] = 0
                            # Use global CHILL_DURATION (or profile if you prefer)
                            chill_time = profile.get("chill_duration", CHILL_DURATION)
                            state["chilldown_until"] = now + chill_time
                            
                            log(u_id, "INTENTION", "RELEASED", "", active_intent.upper()) 
                            log(u_id, "CHILL", "STARTED", "", f"{chill_time}S")
                            save_persistence(force=True)
                    else:
                        # Budget/Window exceeded - Immediate Chilldown
                        state["active_intention"]["name"] = None
                        state["grace_until"] = 0
                        chill_time = profile.get("chill_duration", CHILL_DURATION)
                        state["chilldown_until"] = now + chill_time
                        
                        log(u_id, "INTENTION", "EXPIRED", "BUDGET/WINDOW", active_intent.upper())
                        log(u_id, "CHILL", "STARTED", "", f"{chill_time}S")
                        save_persistence(force=True)

                
                elif state["grace_until"] > 0 and state["active_intention"]["pids"]:
                    state["grace_until"] = 0

                # 2. PID CLEANUP
                for pid in list(state["active_intention"]["pids"].keys()):
                    if not os.path.exists(f"/proc/{pid}"):
                        path_that_died = state["active_intention"]["pids"].pop(pid, None)
                        log(u_id, "EXIT", "", pid, path_that_died)


                # --- Gear 2: Time Update ---
                if now - last_wall_tick >= WALL_TICK_RATE:
                    if active_intent and state["active_intention"]["pids"] and state["grace_until"] == 0:
                        state["intentions"][active_intent] += 1
                        config = profile["intentions"][active_intent]
                        day_rule = config["days"].get(get_day_key(), config["days"].get("def"))
                        if day_rule:
                            expired = not is_in_window(get_seconds_since_midnight(), day_rule.get("time-windows", []))
                            over = state["intentions"][active_intent] >= day_rule.get("time-budget", float("inf"))
                            if expired or over:
                                for pid in list(state["active_intention"]["pids"]):
                                    try: os.kill(pid, signal.SIGKILL)
                                    except: pass
                                    log(u_id, "KILLED", "EXPIRED", pid, active_intent.upper())
                                state["active_intention"]["pids"].clear()

                # Gear 3: Sussy
                if now - last_sussy_tick >= SUSSY_CHECK_RATE:
                    for pid in list(state["sussy_binaries"].keys()):
                        if not os.path.exists(f"/proc/{pid}"): 
                            sussy_data = state["sussy_binaries"].pop(pid, None)
                            if sussy_data: log(u_id, "EXIT", "SUSSY", pid, sussy_data["path"])
                        elif is_gui_process(pid):
                            try: os.kill(pid, signal.SIGKILL)
                            except: pass
                            sussy_data = state["sussy_binaries"].pop(pid, None)
                            if sussy_data: log(u_id, "KILLED", "GUI", pid, sussy_data["path"])

            if now - last_wall_tick >= WALL_TICK_RATE:
                log(0, "SYSTEM", "STATUS", "","")
                last_wall_tick = now
            if now - last_save_tick >= SAVE_INTERVAL:
                save_persistence()
                last_save_tick = now
            if now - last_sussy_tick >= SUSSY_CHECK_RATE: last_sussy_tick = now

    except KeyboardInterrupt:
        print("\nStopping.")
        save_persistence(force=True)

if __name__ == "__main__":
    main()
