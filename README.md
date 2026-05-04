# 🎛 KY23 / KY40 Fusion Controller (Teensy + Windows)

Control Fusion 360 (and other software) using a joystick (KY23) and a rotary encoder (KY40).

## 🎥 Demo

https://youtu.be/Q9Bv5iPM3A8

---

## 🚀 Features

* Joystick orbit control (KY23)
* Encoder zoom (KY40)
* Mode toggle (normal / middle-click per notch)
* No accidental left-clicks
* On-screen overlay (ORB | WHL / MID)
* Cursor centering (long press joystick)

---

## 🧱 Hardware

* Teensy 4.1
* KY23 joystick
* KY40 rotary encoder

---

## 🔌 Wiring

### KY23

* VRx → analog pin
* VRy → analog pin
* SW → digital pin

### KY40

* CLK → digital pin
* DT → digital pin
* SW → digital pin

(All powered in 3.3V)

---

## 💻 Installation (Windows)

1. Install Python
2. Install dependencies:

```
py -m pip install pyserial pyautogui
```

3. Run:

```
run.bat
```

---

## 🎮 Controls

* KY23 → orbit control
* KY23 click → change mode
* KY23 long press → center cursor
* KY40 → zoom
* KY40 click → toggle zoom mode (WHL / MID)

---

## ⚠️ Notes

* KY-040 quality may vary (cheap modules can be noisy)
* For better performance, consider higher quality encoders

---

## 📜 License

MIT License

---

## 🔧 Roadmap

* Per-software profiles (Fusion / Bambu / Windows)
* Better overlay UI
* Standalone executable (no Python required)
* Support for high-end encoders (I2C / SPI)

---


