PyAuto Desktop Documentation
============================

Welcome to the official documentation for **PyAuto Desktop**.
This library offers high-performance, thread-safe desktop automation tools including computer vision and input control.

.. contents:: Table of Contents
   :local:
   :depth: 2

--------------------------------------------------------------------------------

Starter Guide
=============

1. The Inspector Tool
---------------------

PyAuto Desktop includes a GUI tool called the **Inspector**.
Use this to capture screenshots ("needles"), test matches against your screen, and automatically generate the Python code for your script.

.. code-block:: python

   # Opens the GUI for snipping, editing, testing, and code generation
   pyauto_desktop.inspector()

2. Simple Example
-----------------

Here is a basic example of locating an image and clicking it.

.. code-block:: python

   import pyauto_desktop

   # Initialize a session for the primary monitor
   session = pyauto_desktop.Session(
       screen=0,
       source_resolution=(2560, 1440),
       source_dpr=1.25,
       scaling_type="dpr"
   )
    submit_btn = session.locateOnScreen("submit_btn.png", confidence=0.8)
   # Find an image and click it
   if submit_btn:
       print("Button found!")
       session.click("submit_btn.png")

--------------------------------------------------------------------------------

API Reference
=============

.. class:: Session(screen=0, source_resolution=None, source_dpr=None, scaling_type=None)

   The core class that manages screen capture and coordinate translation.

   **Parameters:**

   .. list-table::
      :widths: 20 15 25 40
      :header-rows: 1

      * - Parameter
        - Type
        - Default
        - Description
      * - **screen**
        - ``int``
        - ``0``
        - The logical screen index (0 is primary, 1 is secondary, etc.).
      * - **source_resolution**
        - ``tuple``
        - ``None``
        - The width and height of the monitor where your template images were originally captured.
      * - **source_dpr**
        - ``float``
        - ``None``
        - The DPI scaling factor of the source monitor. If None, it is auto-detected.
      * - **scaling_type**
        - ``str``
        - ``None``
        - The strategy for coordinate translation: ``'dpr'`` or ``'resolution'``. See *Scaling Strategies* below for details.
      * - **direct_input**
        - ``bool``
        - ``False``
        - **WINDOWS ONLY**, Uses ``'pydirectinput'`` (hardware scancodes) instead of ``'pynput'`` (virtual keys). Essential for applications, games, or Citrix/RDP sessions that ignore standard software-simulated input.

   **Scaling Strategies**

   The ``scaling_type`` determines how coordinates are translated when moving between screens with different properties. The correct choice depends on how the target application renders its UI.

   * **'dpr'** (DPI Dependent)
      Best for standard Windows applications (e.g., Web Browsers, Office, Discord). These apps respect the Windows "Scale and layout" settings (100%, 125%, 150%). When the scale changes, these apps resize and reposition their UI elements accordingly.

   * **'resolution'** (Resolution Dependent)
      Best for full-screen applications and games. These applications generally ignore Windows DPI scaling and render 1:1 with the screen's pixel resolution.

   .. tip:: **How to choose the right type**

      To determine if your target application is **DPR** or **Resolution** dependent, perform this simple test:

      1. Open the application.
      2. Go to Windows **Display Settings** -> **Scale and layout**.
      3. Change the scaling percentage (e.g., from 100% to 125%).

      If the application window or UI elements **physically resize or move** on your screen, use ``'dpr'``. If the application UI looks exactly the same (common in full-screen games), use ``'resolution'``.


.. method:: locateOnScreen(image, region=None, grayscale=False, confidence=0.9, source_resolution=None, time_out=0, downscale=3, use_pyramid=True)

   Locates the single best instance of an image on the screen.

   **Parameters:**

   .. list-table::
      :widths: 20 15 25 40
      :header-rows: 1

      * - Parameter
        - Type
        - Default
        - Description
      * - **image**
        - ``str`` | ``object``
        - **Required**
        - File path to the template image or a PIL image object.
      * - **region**
        - ``tuple``
        - ``None``
        - A bounding box ``(x, y, w, h)`` to limit the search area.
      * - **grayscale**
        - ``bool``
        - ``False``
        - If ``True``, converts images to grayscale. Faster, but ignores color information.
      * - **confidence**
        - ``float``
        - ``0.9``
        - Match strictness (0.0 to 1.0). Higher is stricter.
      * - **source_resolution**
        - ``tuple``
        - ``None``
        - Overrides the session source resolution for this specific search.
      * - **source_dpr**
        - ``tuple``
        - ``None``
        - Overrides the session source dpr for this specific search.
      * - **scaling_type**
        - ``tuple``
        - ``None``
        - Overrides the session scaling type for this specific search.
      * - **time_out**
        - ``float``
        - ``0``
        - Maximum seconds to keep retrying if the image is not found immediately.
      * - **downscale**
        - ``int``
        - ``3``
        - Scale factor for the initial pyramid search pass (higher is faster).
      * - **use_pyramid**
        - ``bool``
        - ``True``
        - Whether to use multi-scale pyramid optimization.

   **Example:**

    .. code-block:: python

       start_button = session.locateOnScreen(image='images/start_button.png', region=(100,200,400,500), grayscale=True, confidence=0.85, time_out=3)
       if start_button:
        print("start_button found")

    :noindex:
.. method:: locateAllOnScreen(image, region=None, grayscale=False, confidence=0.9, overlap_threshold=0.5, scaling_type=None, source_resolution=None, time_out=0, downscale=3, use_pyramid=True)

   Locates **all** instances of an image on the screen.

   **Parameters:**

   .. list-table::
      :widths: 20 15 25 40
      :header-rows: 1

      * - Parameter
        - Type
        - Default
        - Description
      * - **image**
        - ``str`` | ``object``
        - **Required**
        - File path to the template image or a PIL image object.
      * - **region**
        - ``tuple``
        - ``None``
        - A bounding box ``(x, y, w, h)`` to limit the search area.
      * - **grayscale**
        - ``bool``
        - ``False``
        - If ``True``, converts images to grayscale. Faster, but ignores color information.
      * - **confidence**
        - ``float``
        - ``0.9``
        - Match strictness (0.0 to 1.0). Higher is stricter.
      * - **overlap_threshold**
        - ``float``
        - ``0.5``
        - Maximum allowed overlap (0.0 to 1.0) between found matches before they are merged.
      * - **source_resolution**
        - ``tuple``
        - ``None``
        - Overrides the session source resolution for this specific search.
      * - **source_dpr**
        - ``tuple``
        - ``None``
        - Overrides the session source dpr for this specific search.
      * - **scaling_type**
        - ``tuple``
        - ``None``
        - Overrides the session scaling type for this specific search.
      * - **time_out**
        - ``float``
        - ``0``
        - Maximum seconds to keep retrying if the image is not found immediately.
      * - **downscale**
        - ``int``
        - ``3``
        - Scale factor for the initial pyramid search pass (higher is faster).
      * - **use_pyramid**
        - ``bool``
        - ``True``
        - Whether to use multi-scale pyramid optimization.

   **Returns:** A list of tuples ``[(x, y, w, h), ...]``.

   **Example:**

    .. code-block:: python

       start_buttons = session.locateAllOnScreen(image='images/start_button.png', region=(100,200,400,500), grayscale=True, confidence=0.85, time_out=3)
       for start_button in start_buttons:
        print(f'Found start_button at {start_button}')
.. method:: locateAny(tasks, time_out=0)

   Searches for a list of different images and returns the **first one** found.
   Useful for detecting application states (e.g., loading finished).

   **Parameters:**

   .. list-table::
      :widths: 20 15 25 40
      :header-rows: 1

      * - Parameter
        - Type
        - Default
        - Description
      * - **tasks**
        - ``list[dict]``
        - **Required**
        - A list of task dictionaries. Each dict must have an ``image`` key (str or object). Optional keys: ``label``, ``confidence``, ``grayscale``, ``region``, ``downscale``.
      * - **time_out**
        - ``float``
        - ``0``
        - Maximum seconds to keep retrying if the image is not found immediately.

   **Returns:** A tuple ``(label, match_tuple)`` or ``None``.

   **Example:**

   .. code-block:: python

        tasks = [{'label': 'connected', 'task': dict(image='images/connected.png', confidence=0.8, grayscale=False)},
        {'label': 'disconnected', 'task': dict(image='images/disconnected.png', confidence=0.8, grayscale=False)}]
        result = session.locateAny(tasks)
        if result:
        label, match = result
        if label == 'connected':
            #start automation
        elif label == 'disconnect':
            #reconnect


.. method:: locateAll(tasks, time_out=0)

   Searches for multiple different images simultaneously and returns **all matches** for every image found.

   **Parameters:**

   .. list-table::
      :widths: 20 15 25 40
      :header-rows: 1

      * - Parameter
        - Type
        - Default
        - Description
      * - **tasks**
        - ``list[dict]``
        - **Required**
        - List of task dictionaries defining what images to look for.
      * - **time_out**
        - ``float``
        - ``0``
        - Maximum seconds to keep retrying if the image is not found immediately.

   **Returns:** A dictionary ``{label: (match)}``.
   **Example:**

   .. code-block:: python

        tasks = [{'label': 'low_health', 'task': dict(image='images/low_health.png', confidence=0.8, grayscale=False)},
        {'label': 'low_mana', 'task': dict(image='images/low_mana.png', confidence=0.8, grayscale=False)}]
        result = session.locateAll(tasks)
        label, match = result
        if label == 'low_health':
            #use health potion
        elif label == 'low_mana':
            #use mana potion


.. method:: click(target=None, y=None, offset=(0,0), button='left', clicks=1, interval=0.2)

   Performs a mouse click.
   It can target a coordinate, a match result, a list of matches, or just click where the mouse currently is.

   **Parameters:**

   .. list-table::
      :widths: 20 15 25 40
      :header-rows: 1

      * - Parameter
        - Type
        - Default
        - Description
      * - **target**
        - ``tuple`` | ``list`` | ``int``
        - ``None``
        - A match tuple ``(x, y, w, h)``, a coordinate tuple ``(x, y)``, a list of matches tuple ``[(x, y, w, h), (x, y, w, h)]``, or ``None`` to click at current mouse position.
      * - **y**
        - ``int``
        - ``None``
        - The Y-coordinate (only used if ``target`` is passed as an X integer).
      * - **offset**
        - ``tuple``
        - ``(0, 0)``
        - Shifts the click position by ``(x, y)`` pixels relative to the target's center.
      * - **button**
        - ``str``
        - ``'left'``
        - Which mouse button to use: ``'left'``, ``'right'``, or ``'middle'``.
      * - **clicks**
        - ``int``
        - ``1``
        - Number of times to click (e.g., 2 for double-click).
      * - **interval**
        - ``float``
        - ``0.2``
        - Delay in seconds between clicks if clicking multiple times or a list of targets.

   **Returns:** A list of  dictionaries ``[{label: [match_list]}, label: [match_list]}]``.


.. method:: moveTo(x, y, duration=0.0)

   Moves the mouse cursor to a specific location.

   **Parameters:**

   .. list-table::
      :widths: 20 15 25 40
      :header-rows: 1

      * - Parameter
        - Type
        - Default
        - Description
      * - **x**
        - ``int``
        - **Required**
        - The target X-coordinate on the screen.
      * - **y**
        - ``int``
        - **Required**
        - The target Y-coordinate on the screen.
      * - **duration**
        - ``float``
        - ``0.0``
        - Time in seconds to slide the mouse to the target. ``0.0`` moves instantly.

.. method:: write(message, interval=0.0)

   Types a string of text using the keyboard.

   **Parameters:**

   .. list-table::
      :widths: 20 15 25 40
      :header-rows: 1

      * - Parameter
        - Type
        - Default
        - Description
      * - **message**
        - ``str``
        - **Required**
        - The text string to type.
      * - **interval**
        - ``float``
        - ``0.0``
        - Delay in seconds between each character typed.

.. method:: press(key)

   Presses a single keyboard key.

   **Parameters:**

   .. list-table::
      :widths: 20 15 25 40
      :header-rows: 1

      * - Parameter
        - Type
        - Default
        - Description
      * - **key**
        - ``str``
        - **Required**
        - The name of the key (e.g., ``"esc"``, ``"f1"``, ``"space"``) or a single character.