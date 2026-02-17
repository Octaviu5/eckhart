# 🧘 Eckhart (v1.0)

### *Protect your focus. Conserve your energy.*

**Eckhart** is a linux python tool designed to help you maintain focus on what truly matters to you. Eckhart acts as a guardian for your attention, ensuring that your energy is directed toward a single purpose rather than being scattered across distractions. 
It monitors and manages process execution at the lowest level, providing a friction-less way to stay present.

## **How Eckhart Works**

### **The Focus Zone**

Eckhart operates on the principle of **One Intention at a Time**. You group your applications into specific**INTENTIONS** (such as *Work*, *Entertainment*, or *Media*).

The moment you open an application, you enter its respective intention zone. To protect your flow, Eckhart will not allow applications from any other zone to open. 

By preventing the launch of distractions at the kernel level, Eckhart removes the mental tax of "resisting temptation" and allows you to remain fully immersed in your intention.


### **The Chilldown (Mindful Transitions)**

After all the binaries belonging to the current intention are closed (either by you, or by the time limits, which wil be explained later in this document.) the intention is released, and Eckhart initiates a **Chilldown period.**.  (Note: A grace period has now been added, to prevent accidental release of the intention, if you accidentally closed the last open binary for a intention but you didnt mean to release the intention yet, you will have a grace period to reopen binaries from that intention, which will cancel the chilldown time.)



For a the duration of the chilldown time, the system enters a state of quietness where no restricted binaries can be launched. 

This forced pause acts as a neural reset, helping you clear your mind before you decide where to direct your energy next.

Also this helps you train yourself to be mindful of your app usage, as it forces you to always remember that if you enter a specific intention, you will have to wait for the chilldown to finish before opening any other intention.


### **Intentional Time Control**

Apart from Focus Zones, Eckhart gives you total authority over your screen time through **Time Rules**.

* **Time Windows:** Define exactly *when* certain binaries are allowed to run during the day.
* **Daily Budgets:** Set a hard limit on *how long* specific applications can be active.

---

## **The Components**

Eckhart is split into four distinct parts located in `/opt/eckhart/`:

1. **The Root Daemon (`eckhart-daemon.py`):** The core engine. It loads **eBPF bytecode** into the kernel to watch every `execve` system call.
2. **Rules Configuration (`rules.json`):** Your personalized map of intentions, zones, and time constraints.
3. **The State Engine (`state.json`):** Eckhart’s long-term memory. It tracks your used time so limits don't reset upon reboot.
4. **User Notifications (`eckhart-user.py`):** The HUD. It runs in your user session and sends real-time desktop notifications via Unix Sockets.

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
sudo mkdir /opt/eckhart/
sudo cp eckhart-daemon.py eckhart-user.py rules.json /opt/eckhart/

```

### **3. Launch the Root Daemon**

```bash
sudo python3 /opt/eckhart/eckhart-daemon.py --verbose

```

### **4. Launch the User notification script**

```bash
python3 /opt/eckhart/eckhart-user.py --verbose

```
*Run the user script in a separate terminal as your normal user to display notifications from Eckhart.*

---

## **The Rule Book (`rules.json`)**


### **1. Intentions & The Chilldown**

Intentions are groups of applications. Opening one locks you into that "State."

* **Enforcement:** While in one Intention, apps from others are killed instantly.
* **Chilldown:** Once the zone is closed, the system enters a mandatory "chilldown period" defined by `chill_duration` (in seconds), preventing all restricted apps from being launched until the chilldown period expires..

### **2. Time Rules (Days, Windows, Budgets)**

* **Hierarchy:** Eckhart looks for the current day (e.g., `"mon"`); if missing, it falls back to `"def"`. **If both are missing, the binary is blocked.**
* **Windows:** Define periods like `["09:00-12:00", "14:00-18:00"]`. Note: Windows **cannot** cross midnight (00:00).
* **Budgets:** Optional `time-budget` in seconds. If omitted, you have infinite access during your windows.

### **3. Authorized & Dev Zones**

* **Authorized Zones:** A whitelist of trusted paths (e.g., `/usr/bin/`). Apps here run freely unless they are explicitly part of an Intention.
* **Dev Zones:** Paths like `/home/user/projects/`. Command-line tools run freely, but any binary attempting to spawn a **GUI** will be killed. This is done to prevent portable distracting apps from being run.

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
ExecStart=/usr/bin/python3 -u /opt/eckhart/eckhart-daemon.py
Restart=always

[Install]
WantedBy=multi-user.target

```

Start with: `sudo systemctl enable --now eckhart`

---
## **Example Ruleset.**

Here is a clean, example `rules.json` You can drop this directly into `/opt/eckhart/rules.json` and start tweaking it to fit your life.

```json
{
  "1000": {
    "intentions": {
      "WORK": {
        "binaries": [
          "inkscape",
          "gimp-3.0",
          "kdenlive",
        ],
        "days": {
          "def": {
            "time-windows": ["08:00-21:00"]
          }
        }
      },
      "BROWSING": {
        "binaries": ["firefox-esr","librewolf", "msedge"],
        "days": {
          "fri": { "time-windows": ["12:00-21:00"], "time-budget": 7200 }
        },
        "single":"true"
      }
    },
    "days_off": {
      "mon": ["librewolf", "chromium"],
      "tue": ["librewolf", "chromium"],
      "wed": ["librewolf", "chromium"],
      "thu": ["librewolf", "chromium"],
      "fri": [],
      "sat": [],
      "sun": []
    },
    "authorized_zones": ["/usr", "/opt", "/bin", "/sbin", "/lib", "/lib64"],

    "dev_zones": ["/path/to/homefolder"],

    "hooks": {
      "wine": "/opt/eckhart/hooks/wine_user1000.py",
    }
  }
}

```

### **A few final notes on this template:**

* **UID:** Is set to `"1000"`. If your `id -u` returns something else, change that top-level key.

* **WORK:** Notice there is no `time-budget` and no days defined for work, other than "def". This means you can access WORK apps everyday for an limitless amount of time between 08:00 and 21:00.

* **BROWSING** Notice there is no `def` for this intention. This means the browsers are blocked every day of the week except Friday.

* **DAYS OFF** this has been added now and it allows to block any binary from an intention for any specific. in this case, whilst there are 3 browsers in the BROWSE intention, only firefox can be accessed all 7 days of the week. This can be useful if you want to further control the time you can access certain binaries.

* **SINGLE** this functionality has been added recently, what it does is it prevents you from running more than one binary from any intention at a time, in this case, since it is true for intention "BROWSING" eckhart will only allow you to run one of said browsers at the time. this is designed to force you to focus on a single task at the time.

* **Dev Zones:** Add any path where you compile your own code here. It'll let you run your CLI tools but will kill any GUI popups.




## HOW TO ACTUALLY USE ECKHART

My personal recommendation is to test eckhart over a period of time. Define a few locks, test them for a few days, see if you're happy with the limits youre impossing on yourself.  
Once you find youre comfortable with your self established limits, you can eckhart into a service and you could also change your account type into a non admin account (so you cant edit the rules). Then you can trust your admin password to a friend or family member, to avoid tampering with the rules and focusing on getting things done.

I personally use a service to send the admin password to the future so i dont have a way to break my rules for a long time.

## **A PERSONAL NOTE**

**I have created this script as a way to help myself keep focused on my other personal goals and projects. And as such, i dont have much time to devote to it. 
I have published it in hopes that it can help someone focus on their on goals and projects. 
It should work as it is, but I cant promise swift maintenance or steady updates.
Feel free to fork it and modify it to your personal liking. 
Attribution is appreciated if you publish your fork.
 .**


## **Credits**

* **Author:** Octavio Villa (@octaviu5)

## ⚖️ License & Terms

Eckhart is released under the **GNU GPLv3 License**.

* **Keep it Open:** If you modify this code or build something on top of it (like a GUI), you MUST release your changes under the same GPLv3 license. You cannot turn this into a closed-source product.
* **No Commercial Hijacking:** You cannot take this engine, wrap it in a pretty box, and sell it as proprietary software.


## **Disclaimer & Support**

**Eckhart is a powerful kernel-level tool. Use it at your own risk.**

* **User Responsibility:** You are solely responsible for your configuration. A bad `rules.json` can prevent your system from launching apps.
* **No Warranty:** This software is provided "as is." I am not liable for any system instability or lost productivity.
* **No Support:** I do not provide technical support or troubleshooting. You are expected to be proficient enough to manage your own setup.

**Stay present.** 
