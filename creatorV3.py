import io
import hashlib
import threading
import time
from dataclasses import dataclass
import json

import requests
import winsound
from PIL import Image, ImageGrab
from concurrent.futures import ThreadPoolExecutor

from google import genai
import flet as ft


# === CONFIGURATION ===
ANKI_URL = "http://localhost:8765"
CAPTURE_INTERVAL_SEC = 0.25
MAX_WORKERS = 4
DEBUG_LOG_PATH = "debug-040211.log"

# Common Gemini models to choose from
GEMINI_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-pro",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
    "gemini-1.0-pro-vision",
    "gemini-3-flash-preview",  # Gemini 3 Flash
]


session = requests.Session()
client: genai.Client | None = None
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)


# region agent log
def debug_log(*, hypothesis_id: str, location: str, message: str, data: dict | None = None, run_id: str = "pre-fix-anki-1") -> None:
    payload = {
        "sessionId": "040211",
        "id": f"log_{int(time.time() * 1000)}",
        "timestamp": int(time.time() * 1000),
        "location": location,
        "message": message,
        "data": data or {},
        "runId": run_id,
        "hypothesisId": hypothesis_id,
    }
    try:
        with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass
# endregion agent log


@dataclass
class Card:
    question: str
    answer: str
    kind: str = "basic"  # "basic" or "cloze"


def make_cloze_text(question: str, answer: str) -> str:
    """Build cloze-deletion text for Anki's Cloze note type."""
    if not answer:
        return question

    # Exact match replacement first
    if answer in question:
        return question.replace(answer, f"{{{{c1::{answer}}}}}", 1)

    # Case-insensitive match
    q_lower = question.lower()
    a_lower = answer.lower()
    if a_lower in q_lower:
        idx = q_lower.index(a_lower)
        original = question[idx : idx + len(answer)]
        return (
            question[:idx]
            + f"{{{{c1::{original}}}}}"
            + question[idx + len(answer) :]
        )

    # Fallback: append cloze with the answer
    return f"{question} {{c1::{answer}}}"


class AnkiBridge:
    def __init__(self, deck_name_getter):
        self.deck_name_getter = deck_name_getter

    def _invoke(self, action, **params):
        try:
            res = session.post(
                ANKI_URL,
                json={"action": action, "version": 6, "params": params},
                timeout=5,
            ).json()
            debug_log(
                hypothesis_id="H3",
                location="creatorV3.py:AnkiBridge._invoke",
                message="Anki invoke response",
                data={
                    "action": action,
                    "ok": bool(res),
                    "has_error": bool(res and res.get("error")),
                },
            )
            return res
        except Exception:
            debug_log(
                hypothesis_id="H3",
                location="creatorV3.py:AnkiBridge._invoke",
                message="Anki invoke exception",
                data={"action": action},
            )
            return None

    def get_decks(self):
        res = self._invoke("deckNames")
        return res.get("result", []) if res else []

    def ensure_deck(self, deck_name: str):
        if not deck_name:
            return
        self._invoke("createDeck", deck=deck_name)

    def get_note_types(self) -> list[str]:
        res = self._invoke("modelNames")
        return res.get("result", []) if res else []

    def get_model_fields(self, model_name: str) -> list[str]:
        if not model_name:
            return []
        res = self._invoke("modelFieldNames", modelName=model_name)
        return res.get("result", []) if res else []

    def add_card(self, card: Card, *, model_name: str, q_field: str, a_field: str) -> tuple[bool, str | None]:
        deck_name = self.deck_name_getter()
        if not deck_name:
            return False, "No deck selected."
        if not model_name:
            return False, "No Anki note type selected."
        if not q_field or not a_field:
            return False, "Question/Answer fields are not selected."
        if q_field == a_field:
            return False, "Question and Answer fields cannot be the same."

        uid = f"<span style='display:none'>{time.time()}</span>"
        note = {
            "deckName": deck_name,
            "modelName": model_name,
            "fields": {
                q_field: card.question + uid,
                a_field: card.answer,
            },
            "options": {"allowDuplicate": True},
        }
        res = self._invoke("addNote", note=note)
        if not res:
            debug_log(
                hypothesis_id="H3",
                location="creatorV3.py:AnkiBridge.add_card",
                message="Anki addNote failed (no response)",
                data={"model": model_name, "q_field": q_field, "a_field": a_field},
            )
            return False, "No response from AnkiConnect. Is Anki open and AnkiConnect installed?"

        if res.get("error"):
            debug_log(
                hypothesis_id="H1",
                location="creatorV3.py:AnkiBridge.add_card",
                message="Anki addNote returned error",
                data={
                    "model": model_name,
                    "q_field": q_field,
                    "a_field": a_field,
                    "error": str(res.get("error"))[:240],
                },
            )
            return False, str(res.get("error"))

        ok = bool(res.get("result"))
        if not ok:
            debug_log(
                hypothesis_id="H2",
                location="creatorV3.py:AnkiBridge.add_card",
                message="Anki addNote returned no result and no error",
                data={"model": model_name, "q_field": q_field, "a_field": a_field},
            )
            return False, "Anki did not return a note id."

        return True, None


class GeminiCardGenerator:
    PROMPT = """
You are a professional STEM flashcard generator.
Analyze the image and produce **high‑quality spaced‑repetition cards**.

You can create two kinds of cards:
- BASIC cards (front/back style) for rules, definitions, direct Q&A.
- CLOZE cards (fill-in-the-blank) for conceptual statements, formulas, or facts best remembered in context.

STRICT OUTPUT FORMAT (NO EXCEPTIONS):
- Output ONLY raw text lines.
- For BASIC cards, use: BASIC | Question | Answer
- For CLOZE cards, use: CLOZE | Sentence containing the answer phrase | Answer phrase only
- Do NOT include pre-written {{c1:: }} syntax; just keep the answer phrase intact in the sentence.
- No markdown, no backticks, no lists, no explanations.
- Use \\( \\) for inline math in the Question/sentence.
- Use \\[ \\] for centered / multi‑line math in the Answer (for formulas).
- Prefer **conceptual understanding** and break complex content into multiple short cards.
- Remove page numbers, watermarks, or irrelevant UI text.

Examples of GOOD lines:
BASIC | What is Gauss's law? | \\[ \\oint_S \\vec{E}\\cdot d\\vec{A} = \\frac{Q_{\\text{enc}}}{\\varepsilon_0} \\]
CLOZE | Gauss's law states that the total electric flux through a closed surface equals the enclosed charge divided by \\(\\varepsilon_0\\). | total electric flux through a closed surface equals the enclosed charge divided by \\(\\varepsilon_0\\)

If multiple cards are appropriate, put each card on its own line.
""".strip()

    def generate_cards_from_image(self, img: Image.Image, model_name: str) -> list[Card]:
        if client is None:
            raise RuntimeError("Gemini API key not configured. Enter your key and press CONNECT.")

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        image_bytes = buf.getvalue()

        resp = client.models.generate_content(
            model=model_name,
            contents=[self.PROMPT, Image.open(io.BytesIO(image_bytes))],
        )

        raw_text = (
            resp.text.strip()
            .replace("```text", "")
            .replace("```", "")
            .strip()
        )

        cards: list[Card] = []
        for line in raw_text.splitlines():
            line = line.strip()
            if not line or "|" not in line:
                continue
            parts = [p.strip() for p in line.split("|")]
            card_type = "basic"
            if len(parts) >= 3:
                type_token = parts[0].lower()
                if type_token in ("basic", "cloze"):
                    card_type = type_token
                    q = parts[1]
                    a = "|".join(parts[2:]).strip()
                else:
                    # Fallback: treat as BASIC Question | Answer
                    q = parts[0]
                    a = "|".join(parts[1:]).strip()
            elif len(parts) == 2:
                q, a = parts
            else:
                continue

            q = q.strip()
            a = a.strip()
            if not q or not a:
                continue
            cards.append(Card(question=q, answer=a, kind=card_type))

        return cards


class RaafatCommandCenter:
    def __init__(self, page: ft.Page):
        self.page = page
        self.page.title = "Ahmed Raafat S26 - INSTANT BRIDGE v16"
        self.page.window_width = 720
        self.page.window_height = 600
        self.page.bgcolor = "#020617"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
        self.page.vertical_alignment = ft.MainAxisAlignment.START

        self.running = False
        self.last_hash: str | None = None
        self.total_images = 0
        self.total_cards = 0
        self.total_errors = 0

        # Services
        self.anki = AnkiBridge(self._get_selected_deck)
        self.card_generator = GeminiCardGenerator()

        self._build_ui()
        self.load_decks()
        self.load_note_types()

    # ===== UI =====
    def _build_ui(self):
        header = ft.Text(
            "STEM BRIDGE COMMAND [INSTANT]",
            size=22,
            weight=ft.FontWeight.BOLD,
            color="#E5E7EB",
        )

        # API key row
        self.api_field = ft.TextField(
            label="Gemini API key",
            password=True,
            can_reveal_password=True,
            dense=True,
            text_size=13,
            bgcolor="#020617",
            border_radius=10,
            width=430,
        )
        self.api_button = ft.Button(
            "Connect",
            on_click=self.connect_api,
        )
        api_row = ft.Row(
            controls=[self.api_field, self.api_button],
            spacing=10,
            alignment=ft.MainAxisAlignment.START,
        )

        # Model row
        self.model_dropdown = ft.Dropdown(
            label="Model",
            dense=True,
            width=430,
            options=[ft.dropdown.Option(m) for m in GEMINI_MODELS],
            value=GEMINI_MODELS[0],
        )
        model_row = ft.Row(
            controls=[self.model_dropdown],
            spacing=10,
            alignment=ft.MainAxisAlignment.START,
        )

        # Deck row
        self.deck_dropdown = ft.Dropdown(
            label="Target deck",
            dense=True,
            width=430,
        )
        refresh_button = ft.OutlinedButton(
            "Refresh decks",
            on_click=self._on_refresh_decks,
        )
        deck_row = ft.Row(
            controls=[self.deck_dropdown, refresh_button],
            spacing=10,
            alignment=ft.MainAxisAlignment.START,
        )

        # Anki note type + field mapping
        self.note_type_dropdown = ft.Dropdown(
            label="Anki note type",
            dense=True,
            width=430,
        )
        refresh_note_types_button = ft.OutlinedButton(
            "Refresh note types",
            on_click=self._on_refresh_note_types,
        )
        note_type_row = ft.Row(
            controls=[self.note_type_dropdown, refresh_note_types_button],
            spacing=10,
            alignment=ft.MainAxisAlignment.START,
        )

        self.q_field_dropdown = ft.Dropdown(
            label="Question field",
            dense=True,
            width=210,
        )
        self.a_field_dropdown = ft.Dropdown(
            label="Answer field",
            dense=True,
            width=210,
        )
        field_map_row = ft.Row(
            controls=[self.q_field_dropdown, self.a_field_dropdown],
            spacing=10,
            alignment=ft.MainAxisAlignment.START,
        )

        # Capture button
        self.toggle_button = ft.Button(
            "START CAPTURE",
            width=620,
            on_click=self.toggle_capture,
        )

        # Log area
        self.log_view = ft.ListView(
            expand=True,
            spacing=4,
            height=260,
            auto_scroll=True,
        )
        log_container = ft.Container(
            content=self.log_view,
            bgcolor="#020617",
            border_radius=8,
            padding=10,
            width=620,
            height=260,
        )

        # Status bar
        self.status_text = ft.Text(
            "Idle",
            size=11,
            color="#9CA3AF",
        )
        status_bar = ft.Container(
            content=self.status_text,
            bgcolor="#020617",
            padding=8,
            width=620,
        )

        layout = ft.Column(
            controls=[
                header,
                api_row,
                model_row,
                deck_row,
                note_type_row,
                field_map_row,
                self.toggle_button,
                log_container,
                status_bar,
            ],
            spacing=14,
            expand=True,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )

        self.page.add(layout)
        self.page.update()

        # Wire up dynamic handlers that some Flet versions don't accept in __init__
        self.note_type_dropdown.on_change = self._on_note_type_change

    def _get_selected_deck(self) -> str:
        return self.deck_dropdown.value or ""

    def _get_selected_model(self) -> str:
        return self.model_dropdown.value or GEMINI_MODELS[0]

    def _get_selected_note_type(self) -> str:
        return self.note_type_dropdown.value or ""

    def _get_selected_q_field(self) -> str:
        return self.q_field_dropdown.value or ""

    def _get_selected_a_field(self) -> str:
        return self.a_field_dropdown.value or ""

    # ===== API key handling =====
    def connect_api(self, e=None):
        global client

        key = (self.api_field.value or "").strip()
        if not key:
            self.set_status("Enter your Gemini API key, then press Connect.")
            self.log("No API key entered.")
            return

        self.set_status("Connecting to Gemini with provided API key...")
        try:
            client = genai.Client(api_key=key)
            # lightweight call to validate key by listing models (best‑effort)
            try:
                _ = client.models.list(page_size=1)
            except Exception:
                # even if this fails, keep the client; errors will surface on use
                pass

            self.api_field.disabled = True
            self.api_button.text = "Connected"
            self.api_button.disabled = True
            self.set_status("Gemini connected. Ready to generate cards.")
            self.log("Gemini API key set successfully.")
            self.page.update()
        except Exception as e:
            client = None
            self.set_status("Failed to connect to Gemini. Check your API key.")
            self.log(f"Gemini connection error: {e}")

    # ===== Logging & status =====
    def log(self, msg: str):
        self.log_view.controls.append(
            ft.Text(
                f"> {msg}",
                size=12,
                color="#A5B4FC",
                font_family="Consolas",
            )
        )
        self.page.update()

    def set_status(self, msg: str):
        self.status_text.value = msg
        self.page.update()

    # ===== Decks & Anki =====
    def load_decks(self):
        decks = self.anki.get_decks()
        if decks:
            self.deck_dropdown.options = [ft.dropdown.Option(d) for d in decks]
            if not self.deck_dropdown.value:
                self.deck_dropdown.value = decks[0]
            self.set_status(f"Decks loaded ({len(decks)} found).")
        else:
            self.set_status("Unable to load decks from Anki.")
        self.page.update()

    def load_note_types(self):
        note_types = self.anki.get_note_types()
        if note_types:
            self.note_type_dropdown.options = [ft.dropdown.Option(n) for n in note_types]
            if not self.note_type_dropdown.value:
                # Prefer your custom model if it exists, otherwise default to first
                preferred = "Raafat Ultra HD"
                self.note_type_dropdown.value = preferred if preferred in note_types else note_types[0]
            self._populate_field_mapping(self.note_type_dropdown.value)
            self.set_status(f"Note types loaded ({len(note_types)} found).")
        else:
            self.set_status("Unable to load note types from Anki.")
        self.page.update()

    def _populate_field_mapping(self, model_name: str):
        fields = self.anki.get_model_fields(model_name)
        self.q_field_dropdown.options = [ft.dropdown.Option(f) for f in fields]
        self.a_field_dropdown.options = [ft.dropdown.Option(f) for f in fields]

        # Best-effort defaults
        if "Question" in fields and "Answer" in fields:
            self.q_field_dropdown.value = "Question"
            self.a_field_dropdown.value = "Answer"
        elif "Front" in fields and "Back" in fields:
            self.q_field_dropdown.value = "Front"
            self.a_field_dropdown.value = "Back"
        elif len(fields) >= 2:
            self.q_field_dropdown.value = fields[0]
            self.a_field_dropdown.value = fields[1]
        elif len(fields) == 1:
            self.q_field_dropdown.value = fields[0]
            self.a_field_dropdown.value = fields[0]
        else:
            self.q_field_dropdown.value = ""
            self.a_field_dropdown.value = ""

    def _on_refresh_note_types(self, e=None):
        self.load_note_types()

    def _on_note_type_change(self, e=None):
        model_name = self._get_selected_note_type()
        if model_name:
            self._populate_field_mapping(model_name)
            self.set_status(f"Selected note type: {model_name}")
            self.page.update()

    def _on_refresh_decks(self, e=None):
        self.load_decks()

    # ===== Capture loop =====
    def toggle_capture(self, e=None):
        if not self.running:
            if client is None:
                self.set_status("Configure Gemini first: enter API key and press Connect.")
                self.log("Cannot start capture: Gemini API key not set.")
                return

            deck = self._get_selected_deck()
            if not deck:
                self.set_status("Select a deck before starting capture.")
                return

            note_type = self._get_selected_note_type()
            q_field = self._get_selected_q_field()
            a_field = self._get_selected_a_field()
            if not note_type or not q_field or not a_field:
                self.set_status("Select Anki note type + map Question/Answer fields before starting.")
                self.log("Cannot start capture: note type or field mapping not configured.")
                return

            self.anki.ensure_deck(deck)
            self.running = True
            self.toggle_button.text = "STOP CAPTURE"
            self.toggle_button.style = ft.ButtonStyle(
                bgcolor={"": "#DC2626"},
                color={"": "#FFFFFF"},
                padding=18,
                shape=ft.RoundedRectangleBorder(radius=10),
            )
            self.log(f"Monitoring clipboard images for deck: {deck}")
            self.set_status(
                f"Listening for new clipboard images... | Images: {self.total_images} | Cards: {self.total_cards} | Errors: {self.total_errors}"
            )

            threading.Thread(target=self._capture_loop, daemon=True).start()
            self.page.update()
        else:
            self.running = False
            self.toggle_button.text = "START CAPTURE"
            self.toggle_button.style = ft.ButtonStyle(
                bgcolor={"": "#16A34A"},
                color={"": "#FFFFFF"},
                padding=18,
                shape=ft.RoundedRectangleBorder(radius=10),
            )
            self.set_status(
                f"Capture stopped. Total Images: {self.total_images} | Cards: {self.total_cards} | Errors: {self.total_errors}"
            )
            self.page.update()

    def _capture_loop(self):
        while self.running:
            try:
                img = ImageGrab.grabclipboard()
                if isinstance(img, Image.Image):
                    h = hashlib.md5(img.tobytes()).hexdigest()
                    if h != self.last_hash:
                        self.last_hash = h
                        self.total_images += 1
                        self.set_status(
                            f"New image detected. Sending to AI... | Images: {self.total_images} | Cards: {self.total_cards} | Errors: {self.total_errors}"
                        )
                        executor.submit(self._process_image_background, img)
            except Exception:
                # Ignore transient clipboard errors and keep listening
                pass

            time.sleep(CAPTURE_INTERVAL_SEC)

    # ===== AI + Anki pipeline =====
    def _process_image_background(self, img: Image.Image):
        self.log("AI analyzing clipboard image...")
        self.set_status(
            f"Generating cards from image... | Images: {self.total_images} | Cards: {self.total_cards} | Errors: {self.total_errors}"
        )

        try:
            model_name = self._get_selected_model()
            cards = self.card_generator.generate_cards_from_image(img, model_name)
            if not cards:
                self.log("No valid Question | Answer pairs found in AI output.")
                self.total_errors += 1
                self.set_status(
                    f"AI returned no valid cards; waiting for next image. | Images: {self.total_images} | Cards: {self.total_cards} | Errors: {self.total_errors}"
                )
                self.last_hash = None
                return

            added = 0
            last_anki_error: str | None = None
            note_type = self._get_selected_note_type()
            q_field = self._get_selected_q_field()
            a_field = self._get_selected_a_field()
            for card in cards:
                if card.kind == "cloze":
                    # Always use Cloze model for cloze cards
                    cloze_text = make_cloze_text(card.question, card.answer)
                    cloze_card = Card(question=cloze_text, answer=card.answer, kind="cloze")
                    ok, err = self.anki.add_card(
                        cloze_card,
                        model_name="Cloze",
                        q_field="Text",
                        a_field="Extra",
                    )
                else:
                    # BASIC front/back-style card using selected model + fields
                    ok, err = self.anki.add_card(
                        card,
                        model_name=note_type,
                        q_field=q_field,
                        a_field=a_field,
                    )
                if ok:
                    added += 1
                else:
                    last_anki_error = err

            if added > 0:
                self.total_cards += added
                self.log(f"DONE: {added} card(s) synced to Anki.")
                self.set_status(
                    f"Last image produced {added} card(s). | Images: {self.total_images} | Cards: {self.total_cards} | Errors: {self.total_errors}"
                )
                winsound.Beep(1000, 200)
            else:
                self.total_errors += 1
                if last_anki_error:
                    self.log(f"Anki rejected all cards. Reason: {last_anki_error}")
                else:
                    self.log("Anki rejected all cards from this image.")
                self.set_status(
                    f"No cards were accepted by Anki. | Images: {self.total_images} | Cards: {self.total_cards} | Errors: {self.total_errors}"
                )
                self.last_hash = None

        except Exception as e:
            self.total_errors += 1
            self.log(f"AI ERROR: {e}")
            self.set_status(
                f"Error while generating cards; waiting for next image. | Images: {self.total_images} | Cards: {self.total_cards} | Errors: {self.total_errors}"
            )
            self.last_hash = None


def main(page: ft.Page):
    RaafatCommandCenter(page)


if __name__ == "__main__":
    ft.run(main)