# STEM Bridge — Clipboard → Gemini → Anki Flashcards

Copy an image of your notes, a textbook page, a slide, or a formula. A few seconds later, finished flashcards are sitting in your Anki deck.

STEM Bridge is a small Windows desktop app (Python + [Flet](https://flet.dev)) that watches your clipboard for images, sends each new image to Google's Gemini API, parses the flashcards the model writes, and adds them to Anki through the [AnkiConnect](https://ankiweb.net/shared/info/2055492159) add-on. It is tuned for STEM material: math and physics come out as LaTeX that Anki renders natively.

---

## Table of contents

1. [What it does](#what-it-does)
2. [Requirements](#requirements)
3. [Installation](#installation)
4. [Set up Anki](#set-up-anki)
5. [Get a Gemini API key](#get-a-gemini-api-key)
6. [Run the app](#run-the-app)
7. [Using the app, step by step](#using-the-app-step-by-step)
8. [Card types and formatting](#card-types-and-formatting)
9. [Configuration](#configuration)
10. [Privacy and security](#privacy-and-security)
11. [Troubleshooting](#troubleshooting)
12. [Known limitations](#known-limitations)
13. [Suggested repository files](#suggested-repository-files)
14. [License and author](#license-and-author)

---

## What it does

```
 You copy an image            STEM Bridge                  Gemini API               Anki
 (Win+Shift+S, Ctrl+C)  --->  detects new image  --->  writes flashcard lines  --->  AnkiConnect
                              (checks every 0.25 s)    BASIC | Q | A                adds notes to
                                                       CLOZE | sentence | answer    your chosen deck
```

- **Clipboard watcher:** checks the clipboard four times a second for a new image. Identical images are skipped (MD5 hash of the pixels), so one copy produces one request.
- **AI card generation:** each new image is sent to the Gemini model you pick. The built-in prompt asks for short, conceptual, spaced-repetition-friendly cards, with LaTeX for math.
- **Two card types:** `BASIC` (front/back) and `CLOZE` (fill-in-the-blank). The app builds the `{{c1::...}}` cloze syntax for you.
- **Your note types, your fields:** pick any Anki note type and map which field is the question and which is the answer.
- **Background processing:** up to 4 images can be processed in parallel, so the UI never freezes while you keep capturing.
- **Live log and counters:** the window shows what happened to every image, plus running totals of images, cards, and errors.
- **Audible confirmation:** a short beep plays when cards were added to Anki.

---

## Requirements

| Requirement | Details |
|---|---|
| Operating system | **Windows** (the script imports `winsound` and uses the Consolas font). See [Known limitations](#known-limitations) for non-Windows notes. |
| Python | **3.10 or newer** (the code uses `X \| None` type syntax that is evaluated at runtime). |
| Anki | Anki desktop, **running** while you use the app. |
| AnkiConnect | The AnkiConnect add-on, code **`2055492159`**. |
| Gemini API key | A key from Google AI Studio (free to create; usage limits depend on Google's current plans). |
| Internet | Needed for the Gemini API. AnkiConnect is local. |
| Python packages | `flet`, `google-genai`, `pillow`, `requests` |

The script is written for the **current Flet API** (`ft.run(...)`, `ft.Button(...)`). Older Flet releases use `ft.app(target=...)` and `ft.ElevatedButton` and will not run this file as-is, so install a recent version of Flet.

**Tested with:** Python `<fill in>`, Flet `<fill in>`, google-genai `<fill in>`, Pillow `<fill in>`, Anki `<fill in>`.
(Run `pip list` in your virtual environment and replace the placeholders so other people can reproduce your setup.)

---

## Installation

### 1. Get the code

```powershell
git clone https://github.com/<your-username>/<repo-name>.git
cd <repo-name>
```

Or download the repository as a ZIP from GitHub (**Code → Download ZIP**) and extract it.

### 2. Create a virtual environment (recommended)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

If PowerShell refuses to run the activation script, allow it for the current window only and try again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\Activate.ps1
```

(In Command Prompt, use `.venv\Scripts\activate.bat` instead.)

### 3. Install the dependencies

```powershell
pip install --upgrade pip
pip install flet google-genai pillow requests
```

Or, if the repository includes a `requirements.txt`:

```powershell
pip install -r requirements.txt
```

> Note the package name: it is **`google-genai`** (the newer Google Gen AI SDK, imported as `from google import genai`), not the older `google-generativeai`.

### 4. Check Python can see everything

```powershell
python -c "import flet, PIL, requests; from google import genai; print('All imports OK')"
```

---

## Set up Anki

### Install AnkiConnect

1. Open Anki.
2. Go to **Tools → Add-ons → Get Add-ons…**
3. Paste the code **`2055492159`** and click **OK**.
4. **Restart Anki** when asked.

### Verify AnkiConnect is working

With Anki open, visit <http://localhost:8765> in your browser. You should see a short message starting with `AnkiConnect`. If the page does not load, Anki is not running or the add-on is not installed.

AnkiConnect listens on `localhost:8765` by default, which is what `ANKI_URL` in the script expects.

### Keep Anki open

STEM Bridge can only talk to Anki while Anki is running. Leave Anki open (it can be in the background) the whole time you capture.

### Know which note types you will use

- **BASIC cards** go to whichever **note type and fields you select in the app**. The Anki built-in **Basic** note type (fields `Front` / `Back`) works out of the box. Custom note types work too.
- **CLOZE cards always go to a note type named exactly `Cloze`**, using the fields `Text` and `Extra`. This is hard-coded (see below).

> **Cloze field-name check.** Anki's stock Cloze note type names its second field **`Back Extra`**, not `Extra`. As far as I know, AnkiConnect ignores field names a note type doesn't have, so cloze cards are still created, but the extra text is dropped. To make the extra text land in the right place, do one of the following:
> - In Anki: **Tools → Manage Note Types → Cloze → Fields →** rename `Back Extra` to `Extra`; **or**
> - In `creatorV3.py`, inside `_process_image_background`, change `a_field="Extra"` to `a_field="Back Extra"`.
>
> If your Anki is set to another language, or you renamed the note type, `Cloze` may not exist under that name. Anki then reports `model was not found: Cloze` — change `model_name="Cloze"` in the same function to match your note type's actual name.

### Math rendering

The prompt asks Gemini to write math with `\( ... \)` (inline) and `\[ ... \]` (display) delimiters. Anki's built-in MathJax support renders both, so formulas look right in the reviewer with no extra add-ons.

---

## Get a Gemini API key

1. Go to <https://aistudio.google.com/apikey> and sign in with a Google account.
2. Click **Create API key** and copy it.
3. Keep it private. You will paste it into the app each time you start it.

Free-tier usage limits (requests per minute/day) change over time and differ per model. **Each new clipboard image is one API request**, so check your current limits in Google AI Studio if you plan to capture many images quickly.

---

## Run the app

1. Start **Anki** (with AnkiConnect installed).
2. In your terminal, from the project folder with the virtual environment active:

```powershell
python creatorV3.py
```

A desktop window opens (default size 720×600, dark theme). The header reads **STEM BRIDGE COMMAND [INSTANT]**.

Right after launch, the app asks Anki for your decks and note types and fills the dropdowns. The status bar at the bottom tells you whether that worked (for example `Decks loaded (5 found).`).

---

## Using the app, step by step

### The window, field by field

| Control | What it does |
|---|---|
| **Gemini API key** | Paste your key here. The text is hidden; click the eye icon to reveal it. |
| **Connect** | Creates the Gemini client with your key. On success the key field locks, the button changes, and the log says `Gemini API key set successfully.` |
| **Model** | Which Gemini model reads your images. Defaults to the first one in the list (`gemini-2.5-flash`). |
| **Target deck** | The Anki deck that receives the cards. Filled from Anki when the app starts. |
| **Refresh decks** | Re-reads the deck list (use it if you opened Anki after the app, or created a new deck). |
| **Anki note type** | The note type used for **BASIC** cards. Defaults to a note type named `Raafat Ultra HD` if you have one, otherwise the first note type Anki returns. |
| **Refresh note types** | Re-reads note types from Anki. |
| **Question field / Answer field** | Which fields of the chosen note type hold the question and the answer. Auto-filled with `Question`/`Answer`, else `Front`/`Back`, else the first two fields. They must be two different fields. |
| **START CAPTURE / STOP CAPTURE** | Starts or stops clipboard monitoring (the button turns red while running). |
| **Log** | A scrolling log of everything the app does. |
| **Status bar** | Current state plus running totals: **Images**, **Cards**, **Errors**. |

### First run: the full workflow

1. **Open Anki.** Leave it running.
2. **Launch the app:** `python creatorV3.py`.
3. **Paste your Gemini API key** and click **Connect**.
4. **Pick a Model.** The default is a good starting point; faster/cheaper models are usually enough for clean notes.
5. **Pick the Target deck.** Create a dedicated deck in Anki first if you want these cards kept separate (for example `Auto Cards`), then click **Refresh decks**.
6. **Pick the Anki note type** for BASIC cards and confirm the **Question field** and **Answer field** are what you expect.
7. Click **START CAPTURE**. The button turns red and the log says `Monitoring clipboard images for deck: ...`.
8. **Copy an image to the clipboard.** Easiest ways on Windows:
   - **Win + Shift + S**, drag a rectangle over any part of your screen (the snip goes to the clipboard).
   - Right-click an image in a browser or PDF viewer → **Copy image**.
   - **Print Screen** for the whole screen.
9. Watch the log:
   - `AI analyzing clipboard image...`
   - `DONE: N card(s) synced to Anki.` and a beep → the cards are in Anki.
10. Click **STOP CAPTURE** when you are finished. Don't leave capture running while you do unrelated things (see [Privacy and security](#privacy-and-security)).

### Tips for good cards

- **Capture one idea at a time.** A tight snip of one definition or derivation gives better cards than a full page.
- **Keep the text readable.** Clear, high-contrast, reasonably large text helps the model.
- **Check the first few cards in Anki's Browser** before batch-capturing, so you know whether to adjust the prompt.
- **Same image twice is ignored.** Identical clipboard content is skipped. To regenerate cards from the same image, copy something different first (or restart the app).
- **There is no undo.** Delete unwanted cards in Anki's **Browse** window.

---

## Card types and formatting

The model is told to answer with plain lines in exactly this format:

```
BASIC | Question | Answer
CLOZE | Sentence containing the answer phrase | Answer phrase only
```

Example output the app can parse:

```
BASIC | What is Gauss's law? | \[ \oint_S \vec{E}\cdot d\vec{A} = \frac{Q_{\text{enc}}}{\varepsilon_0} \]
CLOZE | Gauss's law states that the total electric flux through a closed surface equals the enclosed charge divided by \(\varepsilon_0\). | total electric flux through a closed surface equals the enclosed charge divided by \(\varepsilon_0\)
```

### BASIC cards

The question goes into the **Question field** you selected and the answer into the **Answer field**, using the note type you selected.

### CLOZE cards

The app wraps the answer phrase inside the sentence as `{{c1::...}}` automatically. It tries, in order:

1. an exact match of the answer phrase in the sentence;
2. a case-insensitive match;
3. as a last resort, appending `{{c1::answer}}` to the end of the sentence.

Cloze cards are always added to the `Cloze` note type (fields `Text` and `Extra`), regardless of the note type dropdown. See [Set up Anki](#set-up-anki) for the field-name check.

### Parsing rules (useful if cards look wrong)

- Lines without a `|` are ignored.
- A line starting with something other than `BASIC` or `CLOZE` is treated as `Question | Answer` (BASIC).
- For BASIC and CLOZE lines, everything after the second `|` is treated as the answer, so `|` characters in the *answer* are fine. A `|` in the *question* will split the line in the wrong place.
- If the model returns no valid lines, the log says `No valid Question | Answer pairs found in AI output.`

### Duplicates

Every card is added with Anki's duplicate check turned off, and an invisible timestamp (`<span style='display:none'>…</span>`) is appended to the question field so every card is unique. Re-capturing the same content will create duplicates.

### Customizing the prompt

The card-writing instructions live in `GeminiCardGenerator.PROMPT` in `creatorV3.py`. Edit that text to change the subject focus, card style, or language. Keep the `BASIC | … | …` / `CLOZE | … | …` output format, or the parser will not understand the reply.

---

## Configuration

Settings live at the top of `creatorV3.py`:

| Setting | Default | Meaning |
|---|---|---|
| `ANKI_URL` | `http://localhost:8765` | Where AnkiConnect listens. Change only if you changed AnkiConnect's port. |
| `CAPTURE_INTERVAL_SEC` | `0.25` | How often the clipboard is checked, in seconds. |
| `MAX_WORKERS` | `4` | How many images can be processed at the same time. |
| `DEBUG_LOG_PATH` | `debug-040211.log` | File the app appends diagnostic entries to. |
| `GEMINI_MODELS` | list of model names | The entries shown in the **Model** dropdown. Add or remove names here. |

Other values you may want to change in the code:

| Where | What |
|---|---|
| `load_note_types` | `preferred = "Raafat Ultra HD"` — the note type chosen by default if it exists. Change it to your own note type name. |
| `_process_image_background` | `model_name="Cloze"`, `q_field="Text"`, `a_field="Extra"` — where cloze cards go. |
| `RaafatCommandCenter.__init__` | Window title (`self.page.title`), window size, background color. |
| `GeminiCardGenerator.PROMPT` | The instructions sent to Gemini with every image. |

### About the models list

The dropdown offers several Gemini model names. Google retires and renames models over time, and some names (especially `-preview` ones or older generations) may not be available to your key. If the log shows an error such as a 404 or "model not found", choose a different model, or edit `GEMINI_MODELS` to match what your key can use.

---

## Privacy and security

- **Your images leave your computer.** Every image the app detects is uploaded to Google's Gemini API. While **START CAPTURE** is on, *any* image you copy — including screenshots of private messages, grades, or personal documents — is sent. Stop capture when you are not actively making cards.
- **Check Google's data terms.** How Google handles API inputs depends on your plan (for example, free-tier content may be used to improve Google products). Read the current Gemini API terms before sending anything sensitive.
- **Your API key is never saved by this app.** It is typed into the window each run and kept only in memory. The script contains no secrets, so it is safe to publish. Never hard-code a key into the file, and never commit one. If a key is ever exposed, revoke it in Google AI Studio and create a new one.
- **Anki stays local.** AnkiConnect traffic goes to `localhost` only.
- **The debug log.** The app appends JSON lines to `debug-040211.log` in the folder you run it from. Entries contain AnkiConnect action names, model/field names, and truncated Anki error messages. They do **not** contain your API key or your images. The file is safe to delete at any time. Keep it out of Git (see [Suggested repository files](#suggested-repository-files)).

---

## Troubleshooting

### Setup and startup

| Symptom | Likely cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'flet'` (or `PIL`, `google`, `requests`) | Dependencies not installed in the Python you are running | Activate your virtual environment, then `pip install flet google-genai pillow requests` |
| `ImportError: cannot import name 'genai' from 'google'` | The wrong Google package is installed | `pip uninstall google-generativeai` then `pip install google-genai` |
| `TypeError: 'module' object is not callable` at `ft.run(main)`, or `AttributeError` on `ft.run` / `ft.Button` | Flet is too old (or a very different version) for this script | `pip install --upgrade flet`. If a newer Flet breaks something, install the exact version listed under **Tested with**. |
| `ModuleNotFoundError: No module named 'winsound'` | You are not on Windows | See [Known limitations](#known-limitations) |
| A syntax error on lines containing `str \| None` | Python older than 3.10 | Install Python 3.10 or newer |
| PowerShell: `running scripts is disabled on this system` | Execution policy blocks venv activation | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` |

### Anki problems

| Symptom | Likely cause | Fix |
|---|---|---|
| Status: `Unable to load decks from Anki.` / `Unable to load note types from Anki.` | Anki is closed, AnkiConnect is not installed, or the port differs | Open Anki, install AnkiConnect (`2055492159`), restart Anki, check <http://localhost:8765>, then click **Refresh decks** / **Refresh note types** |
| Log: `No response from AnkiConnect. Is Anki open and AnkiConnect installed?` | Anki closed mid-session, or Anki is blocked by a dialog | Reopen Anki, close any open dialog, check the localhost URL again |
| Deck dropdown is empty | Anki was not running when the app launched | Start Anki, click **Refresh decks** |
| Log: `Anki rejected all cards. Reason: model was not found: <name>` | The note type does not exist under that name (often `Cloze` in a localized or customized Anki) | Pick an existing note type for BASIC cards; for cloze, change `model_name="Cloze"` in the code to your real note type name |
| Log: `Question and Answer fields cannot be the same.` | Both field dropdowns point to one field | Choose two different fields |
| Log: `Select Anki note type + map Question/Answer fields before starting.` | Note type or fields are empty | Select a note type; click **Refresh note types** if the list is empty |
| Cloze cards appear but the extra text is missing | Stock Cloze names its second field `Back Extra`, not `Extra` | See the cloze field-name check in [Set up Anki](#set-up-anki) |
| Cards appear in the wrong deck | Wrong **Target deck** selected | Re-select the deck before starting capture |

### Gemini problems

| Symptom | Likely cause | Fix |
|---|---|---|
| `Enter your Gemini API key, then press Connect.` | Key field is empty | Paste your key and click **Connect** |
| `Configure Gemini first: enter API key and press Connect.` when starting capture | Not connected yet | Click **Connect** first |
| `Gemini connection error` or log lines starting `AI ERROR:` mentioning API key / 400 / 403 | Invalid, expired, or restricted key | Create a new key in Google AI Studio and reconnect (restart the app to enter a new key — the field locks after a successful connection) |
| `AI ERROR:` mentioning 404 / model not found | The selected model name is unavailable to your key | Choose a different **Model**, or edit `GEMINI_MODELS` |
| `AI ERROR:` mentioning 429 / quota / rate limit | Free-tier or per-minute limit reached | Stop capture, wait, capture fewer images, or use a model/plan with higher limits |
| `No valid Question \| Answer pairs found in AI output.` | The image had no usable text, or the model ignored the format | Capture a clearer, tighter image; try another model |

### Capture problems

| Symptom | Likely cause | Fix |
|---|---|---|
| Nothing happens after copying | Capture is not running, or what you copied is not an image (for example copied text, or a file in Explorer) | Make sure the button says **STOP CAPTURE**; use **Win+Shift+S** or **Copy image** |
| The second copy of the same image does nothing | Identical images are deliberately ignored | Copy something different first, or restart the app |
| **The Errors counter keeps climbing and the same image is processed again and again** | After any failure, the app forgets which image it last saw, so the *same* clipboard image is immediately retried — and keeps being retried until it works | Click **STOP CAPTURE** right away, fix the cause shown in the log (Anki closed, wrong note type/fields, bad model, quota), then copy the image again and restart capture. Don't walk away while errors are happening: each retry is an API request. |
| Cards are created but look unformatted | LaTeX delimiters not rendered | Make sure you use a normal Anki note type with MathJax support (default behavior); check the card in the Anki reviewer, not only the editor |
| No beep | Beep only plays when at least one card was added | Check the log for `DONE:` |

---

## Known limitations

- **Windows only as written.** The script imports `winsound` at the top and calls `winsound.Beep(...)` after successful syncs, and the log uses the Consolas font. On macOS/Linux you would need to remove the `import winsound` line and the `winsound.Beep(1000, 200)` call (or replace them with another sound method). Clipboard image capture through Pillow's `ImageGrab.grabclipboard()` also needs extra system tools on Linux (such as `xclip` or `wl-paste`), so macOS/Linux are untested here.
- **Images only.** Copied text and copied files are ignored.
- **No preview or approval step.** Cards go straight into Anki. Review them in Anki's Browser afterward.
- **Cloze details are hard-coded** to a note type called `Cloze` with fields `Text` and `Extra`.
- **Failed images are retried automatically** (see Troubleshooting) — stop capture when errors appear.
- **`|` inside a question** can split the line wrongly.
- **AI output varies.** Model quality, formatting, and LaTeX correctness differ by model and by image. Always spot-check new decks.
- **Leftover personal defaults.** The window title ("Ahmed Raafat S26 - INSTANT BRIDGE v16") and the preferred note type name (`Raafat Ultra HD`) are the author's own; change them to fit your setup.

---

## Suggested repository files

Add these next to `creatorV3.py` before publishing.

**`requirements.txt`** (replace the versions with your tested ones):

```
flet
google-genai
pillow
requests
```

**`.gitignore`**

```
# Python
__pycache__/
*.pyc
.venv/
venv/

# App debug log
debug-*.log

# Secrets (never commit keys)
.env
*.key
```

---

## License and author

Add a `LICENSE` file to tell others what they may do with your code (for example MIT; GitHub can generate one when you create the repository or via **Add file → Create new file → LICENSE**). Until a license is added, the code is "all rights reserved" by default.

Built by Ahmed Raafat.
