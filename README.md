# 🧘 Eckhart (v1.0)

### *Protect your focus. Conserve your energy.*

**Eckhart** is a tool designed to help you maintain focus on what truly matters. In an age of endless digital noise, Eckhart acts as a guardian for your attention, ensuring that your energy is directed toward a single purpose rather than being scattered across distractions.

## **How Eckhart Works**

### **The Focus Zone**

Eckhart operates on the principle of **One Thing at a Time**. You define your world into specific **Focus Zones** (such as *Work*, *Entertainment*, or *Media*).

The moment you open an application, you enter its respective Zone. To protect your flow, Eckhart will not allow applications from any other Zone to open. By physically preventing the launch of distractions at the kernel level, Eckhart removes the mental tax of "resisting temptation" and allows you to remain fully immersed.

### **The Chilldown (Mindful Transitions)**

Presence isn't just about working hard; it's about transitioning well. When you finish a task and close all applications within a Focus Zone, Eckhart initiates a **Chilldown**.

For a duration you define, the system enters a state of quiet where no restricted binaries can be launched. This forced pause acts as a neural reset, helping you clear your mind before you decide where to direct your energy next.

### **Intentional Time Control**

Beyond Focus Zones, Eckhart gives you total authority over your screen time through **Time Rules**.

* **Windows of Presence:** Define exactly *when* certain binaries are allowed to run during the day.
* **Daily Budgets:** Set a hard limit on *how long* specific applications can be active.

---

## **The Components**

Eckhart is split into four distinct parts located in `/opt/eckhart/`:

1. **The Root Daemon (`eckhart-root.py`):** The core engine. It loads **eBPF bytecode** into the kernel to watch every `execve` system call.
2. **Rules Configuration (`rules.json`):** Your personalized map of intentions, zones, and time constraints.
3. **The State Engine (`state.json`):** Eckhart’s long-term memory. It tracks your used time so limits don't reset upon reboot.
4. **User Notifications (`eckhart-monitor.py`):** The HUD. It runs in your user session and sends real-time desktop notifications via Unix Sockets.

---

## **How to Set Up Eckhart**

### **1. Install Dependencies**

```bash
sudo apt update
sudo apt install bpfcc-tools linux-headers-$(uname -r) python3-bpfcc libnotify-bin

```

### **2. Organize Files**

Eckhart is designed to live in `/opt/eckhart/`.

```bash
sudo cp eckhart-root.py eckhart-monitor.py rules.json /opt/eckhart/

```

### **3. Launch the Guardian**

```bash
sudo python3 /opt/eckhart/eckhart-root.py --verbose

```

*Run the monitor script in a separate terminal as your normal user to receive HUD updates.*

---

## **The Rules of Engagement (`rules.json`)**

### **1. Intentions & The Chilldown**

Intentions are groups of applications. Opening one locks you into that "State."

* **Enforcement:** While in one Intention, apps from others are killed instantly.
* **Chilldown:** Once the zone is closed, the system enters a mandatory "quiet period" defined by `chill_duration` (in seconds), blocking all restricted apps.

### **2. Time Rules (Days, Windows, Budgets)**

* **Hierarchy:** Eckhart looks for the current day (e.g., `"mon"`); if missing, it falls back to `"def"`. **If both are missing, the binary is blocked.**
* **Windows:** Define periods like `["09:00-12:00", "14:00-18:00"]`. Note: Windows **cannot** cross midnight (00:00).
* **Budgets:** Optional `time-budget` in seconds. If omitted, you have infinite access during your windows.

### **3. Authorized & Dev Zones**

* **Authorized Zones:** A whitelist of trusted paths (e.g., `/usr/bin/`). Apps here run freely unless they are explicitly part of an Intention.
* **Dev Zones:** Paths like `/home/user/projects/`. Command-line tools run freely, but any binary attempting to spawn a **GUI** will be killed.

### **4. Custom Hooks (Advanced)**

You can define a path to a Python script in `rules.json` under `hooks`. When the specified binary launches, Eckhart triggers your script, passing the **PID** and **UID** as arguments. No hooks are provided; advanced users must implement their own logic.

---

## **Automation (Systemd Service)**

To run Eckhart automatically on boot, create `/etc/systemd/system/eckhart.service`:

```ini
[Unit]
Description=Eckhart eBPF Focus Daemon
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/eckhart
ExecStart=/usr/bin/python3 /opt/eckhart/eckhart-root.py
Restart=always

[Install]
WantedBy=multi-user.target

```

Start with: `sudo systemctl enable --now eckhart`

---

## **Disclaimer & Support**

**Eckhart is a powerful kernel-level tool. Use it at your own risk.**

* **User Responsibility:** You are solely responsible for your configuration. A bad `rules.json` can prevent your system from launching apps.
* **No Warranty:** This software is provided "as is." I am not liable for any system instability or lost productivity.
* **No Support:** This is a personal project. I do not provide technical support or troubleshooting. You are expected to be proficient enough to manage your own setup.

**Stay present.**	




Here is a clean, example `rules.json` You can drop this directly into `/opt/eckhart/rules.json` and start tweaking it to fit your life.

```json
{
  "1000": {
    "intentions": {
      "work": ["code", "terminal", "emacs", "gcc", "make"],
      "learning": ["anki", "obsidian", "zathura"],
      "leisure": ["vlc", "steam", "chromium", "firefox"]
    },
    "time_rules": {
      "leisure": {
        "binaries": ["vlc", "chromium", "firefox"],
        "days": {
          "mon": { 
            "time-windows": ["20:00-22:00"], 
            "time-budget": 1800 
          },
          "sat": { 
            "time-windows": ["10:00-23:59"] 
          },
          "def": { 
            "time-windows": ["19:00-21:00"], 
            "time-budget": 3600 
          }
        }
      },
      "gaming": {
        "binaries": ["steam"],
        "days": {
          "sat": { "time-windows": ["14:00-22:00"], "time-budget": 7200 },
          "sun": { "time-windows": ["14:00-20:00"], "time-budget": 3600 }
        }
      }
    },
    "authorized_zones": [
      "/usr/bin/",
      "/bin/",
      "/usr/sbin/",
      "/sbin/",
      "/usr/local/bin/",
      "/opt/"
    ],
    "dev_zones": [
      "/home/user/projects/",
      "/home/user/go/bin/"
    ],
    "chill_duration": 60,
    "hooks": {
      "steam": "/opt/eckhart/hooks/on_gaming_start.py"
    }
  }
}

```

### **A few final notes on this template:**

* **UID:** Is set to `"1000"`. If your `id -u` returns something else, change that top-level key.
* **The "Leisure" Saturday Rule:** Notice there is no `time-budget` for Saturday. This means you have infinite time as long as you are inside that one window.
* **The "Gaming" Sunday Rule:** Notice there is no `def` for gaming. This means Steam is physically blocked every day of the week except Saturday and Sunday.
* **Dev Zones:** Add any path where you compile your own code here. It'll let you run your CLI tools but will kill any accidental GUI popups.



## **Credits**

* **Author:** Octavio Villa (@octaviu5)

## ⚖️ License & Terms

Eckhart is released under the **GNU GPLv3 License**.

* **Keep it Open:** If you modify this code or build something on top of it (like a GUI), you MUST release your changes under the same GPLv3 license. You cannot turn this into a closed-source product.
* **No Commercial Hijacking:** You cannot take this engine, wrap it in a pretty box, and sell it as proprietary software.
* **Zero Support / Zero Liability:** This is a "take it or leave it" project. I am not a help desk. If it breaks your setup, you fix it.
