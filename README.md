# pyauto-desktop

**The resolution-agnostic, high-performance automation library for Python.**

📘 **Documentation:** [Read the full docs here](https://pyauto-desktop.readthedocs.io/en/latest/)

Built on `mss` and `OpenCV`. Designed for scalability. Includes a built-in GUI Inspector.

`pyauto-desktop` is a drop-in replacement for `pyautogui` designed for developers who need their automation scripts to work across different monitors, resolutions, and scaling settings (DPR).

It introduces the concept of a **Session**: a portable definition of your development environment that allows your code to auto-scale intelligently on any target machine.

---

## Why Switch?

Most automation libraries fail when moved from a Dev machine (e.g., 4K monitor, 125% scale) to a Production machine (e.g., 1080p, 100% scale). `pyauto-desktop` solves this mathematically.

| Feature                  | pyauto-desktop                                                                        | pyautogui |
|:-------------------------|:--------------------------------------------------------------------------------------| :--- |
| **Cross-Resolution&DPR** | **Automatic.** Uses `Session` logic to scale coordinates & images automatically.      | **Manual.** Scripts break if resolution changes. |
| **Performance**          | **Up to 5x Faster.** Uses `mss` & Pyramid Template Matching & Image caching.          | Standard speed. |
| **Logic**                | `locateAny` / `locateAll` built-in. Finds first or all matches from a list of images. | Requires complex `for` loops / `try-except` blocks. |
| **Tooling**              | **Built-in GUI Inspector** to snip, edit, test, and generate code.                    | None. Requires external tools. |
| **Backend**              | `opencv-python`, `mss`, `pynput`                                                      | `pyscreeze`, `pillow`, `mouse` |

## 💻 Operating System Support

* **Windows:** ✅ **Tested and Supported.**
* **Mac / Linux:** ⚠️ **Experimental.** While the underlying libraries (OpenCV, Qt6) are cross-platform, these environments have not been verified. Use at your own risk.

## 📦 Installation

`pyauto-desktop` relies on robust standard libraries like OpenCV and Qt6.

```bash
pip install pyauto-desktop
```

## The Core Concept: The "Session"

In `pyautogui`, you write code for *your* screen. If you share that script, it usually fails on other screens.

In `pyauto-desktop`, you define a **Session** that records your **source resolution** and **DPR**. At runtime, the library compares your source environment with the current machine and automatically scales **all clicks and image searches**.

The result: the same script works across 1080p, 1440p, 4K, and retina displays without modification.

---

## 1. The GUI Inspector (No More Guessing Coordinates)

You don’t write the automation code by hand. Instead, open the Inspector to:

- Snip UI elements directly from the screen
- Test image matches in real time
- Auto-generate production-ready Python code

```python
import pyauto_desktop

# Opens the snipping and code generation tool
pyauto_desktop.inspector()
```

---

## 2. Generated Code Example

The code below works on a 1080p screen, a 4K screen, or a retina display **without modification**.

```python
import pyauto_desktop

# Define the environment where you CREATED the script (e.g., your 1440p monitor)
# The library detects the CURRENT screen at runtime and scales accordingly
session = pyauto_desktop.Session(
    screen=1,
    source_resolution=(2560, 1440),
    source_dpr=1.25,
    scaling_type="dpr"
)

# Search for the image
# 'grayscale' and 'confidence' behave like standard automation tools
# 'use_pyramid=True' (default) handles slight size variations in the UI
image = session.locateOnScreen(
    'images/submit_btn.png',
    grayscale=True,
    confidence=0.9
)

if image:
    session.click(image)
```

---

### ⚠️ Important Note on Auto-Scaling & Confidence

The auto-scaling logic is robust, but not perfect. It is possible when an image is scaled down, a small amount of pixel detail can be lost, which affects template matching that could require confidence score tweaking.

---
