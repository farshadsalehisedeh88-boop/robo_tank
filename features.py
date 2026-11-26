"""پنجره‌های نقشه، لیست مسیرهای ذخیره‌شده، هوش مصنوعی، و تحریک ماژول‌ها (Kivy)."""
import math
import threading

from kivy.clock import Clock
from kivy.graphics import Color, Ellipse, Line, Rectangle, Triangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

import ai
from automation import summarize

MIN_SPAN_CM = 100.0


def _button(text, callback, **kwargs):
    btn = Button(text=text, **kwargs)
    btn.bind(on_release=lambda _: callback())
    return btn


def _wrap_label(text="", **kwargs):
    lbl = Label(text=text, halign="left", valign="top", **kwargs)
    lbl.bind(size=lambda w, s: setattr(w, "text_size", s))
    return lbl


class MapView(Widget):
    def __init__(self, tracker, **kwargs):
        super().__init__(**kwargs)
        self.tracker = tracker
        self.grid_cm = 0
        self.bind(pos=self.redraw, size=self.redraw)

    @staticmethod
    def _nice_step(scale):
        for step in (5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000):
            if step * scale >= dp(40):
                return step
        return 5000

    def redraw(self, *args):
        self.canvas.clear()
        with self.canvas:
            Color(0.09, 0.09, 0.11, 1)
            Rectangle(pos=self.pos, size=self.size)
        tr = self.tracker
        if tr is None or self.width < 20 or self.height < 20:
            return

        pts = list(tr.points) + [(tr.x, tr.y)]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        span = max(max(xs) - min(xs), max(ys) - min(ys), MIN_SPAN_CM)
        pad = dp(24)
        scale = max(1e-6, (min(self.width, self.height) - 2 * pad) / span)
        mx = (max(xs) + min(xs)) / 2.0
        my = (max(ys) + min(ys)) / 2.0

        def tx(x):
            return self.center_x + (x - mx) * scale

        def ty(y):
            return self.center_y + (y - my) * scale

        step = self._nice_step(scale)
        self.grid_cm = step
        half_w = self.width / 2.0 / scale
        half_h = self.height / 2.0 / scale

        with self.canvas:
            Color(0.20, 0.20, 0.24, 1)
            k = math.floor((mx - half_w) / step)
            count = 0
            while k * step <= mx + half_w and count < 80:
                x = tx(k * step)
                Line(points=[x, self.y, x, self.y + self.height], width=1)
                k += 1
                count += 1
            k = math.floor((my - half_h) / step)
            count = 0
            while k * step <= my + half_h and count < 80:
                y = ty(k * step)
                Line(points=[self.x, y, self.x + self.width, y], width=1)
                k += 1
                count += 1

            flat = []
            for px, py in tr.points:
                flat += [tx(px), ty(py)]
            flat += [tx(tr.x), ty(tr.y)]
            Color(0.30, 0.75, 1.0, 1)
            Line(points=flat, width=2)

            r = dp(5)
            Color(0.25, 0.85, 0.45, 1)
            Ellipse(pos=(tx(0) - r, ty(0) - r), size=(2 * r, 2 * r))

            rx, ry = tx(tr.x), ty(tr.y)
            h = math.radians(tr.heading)
            dx, dy = math.cos(h), math.sin(h)
            size = dp(9)
            Color(1.0, 0.35, 0.30, 1)
            Triangle(points=[
                rx + dx * size, ry + dy * size,
                rx - dx * size * 0.6 - dy * size * 0.6, ry - dy * size * 0.6 + dx * size * 0.6,
                rx - dx * size * 0.6 + dy * size * 0.6, ry - dy * size * 0.6 - dx * size * 0.6,
            ])


class MapPopup(Popup):
    def __init__(self, panel, **kwargs):
        body = BoxLayout(orientation="vertical", spacing=dp(6), padding=dp(4))
        super().__init__(title="MAP (estimated path)", content=body, size_hint=(0.95, 0.95),
                         auto_dismiss=False, **kwargs)
        self.panel = panel
        self.map = MapView(panel.tracker, size_hint_y=0.66)
        self.info = Label(text="", font_size="13sp", size_hint_y=0.1)

        cal = BoxLayout(size_hint_y=0.12, spacing=dp(6))
        cal.add_widget(Label(text="cm/s", size_hint_x=None, width=dp(48)))
        self.cm_in = TextInput(text=f"{panel.tracker.cm_per_sec:g}", multiline=False,
                               input_filter="float", font_size="14sp")
        cal.add_widget(self.cm_in)
        cal.add_widget(Label(text="deg/s", size_hint_x=None, width=dp(52)))
        self.deg_in = TextInput(text=f"{panel.tracker.deg_per_sec:g}", multiline=False,
                                input_filter="float", font_size="14sp")
        cal.add_widget(self.deg_in)
        cal.add_widget(_button("SET", self._apply_cal, size_hint_x=None, width=dp(64)))

        buttons = BoxLayout(size_hint_y=0.12, spacing=dp(8))
        buttons.add_widget(_button("CLEAR", self._clear))
        buttons.add_widget(_button("CLOSE", self.dismiss))

        for w in (self.map, self.info, cal, buttons):
            body.add_widget(w)
        self._ev = Clock.schedule_interval(self._tick, 0.25)
        self._tick(0)

    def _tick(self, dt):
        tr = self.panel.tracker
        self.map.redraw()
        turned = (tr.heading - 90.0 + 180.0) % 360.0 - 180.0
        self.info.text = (f"dist {tr.distance:.0f} cm   pos ({tr.x:.0f}, {tr.y:.0f})   "
                          f"turn {turned:.0f} deg   grid {self.map.grid_cm} cm")

    def _apply_cal(self):
        self.panel.set_calibration(self.cm_in.text, self.deg_in.text)
        self.cm_in.text = f"{self.panel.tracker.cm_per_sec:g}"
        self.deg_in.text = f"{self.panel.tracker.deg_per_sec:g}"

    def _clear(self):
        self.panel.tracker.reset()
        self._tick(0)

    def on_dismiss(self):
        self._ev.cancel()


class SensorsPopup(Popup):
    """نمایش وضعیت تحریک ماژول‌ها و سنسورهای خط روی ESP."""

    def __init__(self, panel, **kwargs):
        body = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        super().__init__(title="MODULE TRIGGERS & SENSORS", content=body, size_hint=(0.90, 0.85),
                         auto_dismiss=False, **kwargs)
        self.panel = panel
        self.status_lbl = _wrap_label("Reading module states...", font_size="14sp")
        self.bars_box = BoxLayout(orientation="horizontal", spacing=dp(8), size_hint_y=0.35)
        self.sensor_btns = {}
        for key in ("L", "C", "R", "LOST", "AUTO", "HW"):
            b = Button(text=f"{key}: --", background_color=(0.22, 0.22, 0.26, 1))
            self.sensor_btns[key] = b
            self.bars_box.add_widget(b)

        btns = BoxLayout(size_hint_y=0.18, spacing=dp(8))
        btns.add_widget(_button("REFRESH", self._refresh_now))
        btns.add_widget(_button("CLOSE", self.dismiss))

        body.add_widget(self.bars_box)
        body.add_widget(self.status_lbl)
        body.add_widget(btns)

        self._ev = Clock.schedule_interval(self._refresh_now, 0.35)
        self._refresh_now(0)

    def _refresh_now(self, dt=0):
        self.panel.request_sensor_poll()
        st = self.panel.last_sensor_state
        if not st:
            self.status_lbl.text = "No sensor telemetry yet. Check ESP connection (/sensors)."
            return
        mapping = {
            "L": ("L", bool(st.get("l"))),
            "C": ("C", bool(st.get("c"))),
            "R": ("R", bool(st.get("r"))),
            "LOST": ("LOST", bool(st.get("lost"))),
            "AUTO": ("AUTO", bool(st.get("auto"))),
            "HW": ("LN_HW", bool(st.get("en"))),
        }
        for key, (label, active) in mapping.items():
            btn = self.sensor_btns[key]
            btn.text = f"{label}: {'ON' if active else 'OFF'}"
            if key == "LOST":
                btn.background_color = (0.75, 0.22, 0.22, 1) if active else (0.18, 0.45, 0.25, 1)
            else:
                btn.background_color = (0.18, 0.65, 0.35, 1) if active else (0.22, 0.22, 0.26, 1)

        self.status_lbl.text = (
            f"Line HW enabled: {st.get('en')} | Auto active: {st.get('auto')}\n"
            f"Sensors L/C/R: {st.get('l')}/{st.get('c')}/{st.get('r')} | Line lost: {st.get('lost')}\n"
            f"AI line cfg -> spd:{st.get('spd')} turn:{st.get('turn')} "
            f"search:{st.get('sdir')} ({st.get('ssec')}s)"
        )

    def on_dismiss(self):
        self._ev.cancel()


class RecordsPopup(Popup):
    def __init__(self, panel, **kwargs):
        body = BoxLayout(orientation="vertical", spacing=dp(6), padding=dp(4))
        super().__init__(title="SAVED PATHS", content=body, size_hint=(0.95, 0.95),
                         auto_dismiss=False, **kwargs)
        self.panel = panel

        top = BoxLayout(size_hint_y=0.13, spacing=dp(8))
        top.add_widget(_button("STOP PLAYING", self.panel.stop_program))
        top.add_widget(_button("CLOSE", self.dismiss))

        scroll = ScrollView()
        self.grid = GridLayout(cols=1, size_hint_y=None, spacing=dp(4))
        self.grid.bind(minimum_height=self.grid.setter("height"))
        scroll.add_widget(self.grid)

        body.add_widget(top)
        body.add_widget(scroll)
        self.refresh()

    def refresh(self):
        self.grid.clear_widgets()
        lib = self.panel.library
        names = lib.names()
        if not names:
            self.grid.add_widget(Label(text="Nothing saved yet. Use REC or AI.",
                                       size_hint_y=None, height=dp(48)))
        for name in names:
            row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(6))
            row.add_widget(Label(text=name, size_hint_x=0.38))
            row.add_widget(Label(text=f"{lib.duration(name):.1f}s", size_hint_x=0.2))
            row.add_widget(_button("PLAY", lambda n=name: self._play(n), size_hint_x=0.24))
            row.add_widget(_button("DEL", lambda n=name: self._delete(n), size_hint_x=0.18))
            self.grid.add_widget(row)

    def _play(self, name):
        events = self.panel.library.get(name)
        if events:
            self.dismiss()
            self.panel.run_events(events)

    def _delete(self, name):
        self.panel.library.delete(name)
        self.refresh()


class AIPopup(Popup):
    """جمله را بنویس -> PLAN (برنامه حرکتی) یا LINE AI (تنظیم هوشمند لاینر و جست‌وجوی خط)."""

    def __init__(self, panel, **kwargs):
        body = BoxLayout(orientation="vertical", spacing=dp(6), padding=dp(4))
        super().__init__(title="AI (Gemini)", content=body, size_hint=(0.95, 0.95),
                         auto_dismiss=False, **kwargs)
        self.panel = panel
        self.events = None
        self.line_cfg = None

        key_row = BoxLayout(size_hint_y=0.11, spacing=dp(6))
        key_row.add_widget(Label(text="KEY", size_hint_x=None, width=dp(44)))
        self.key_in = TextInput(text=panel.api_key, multiline=False, password=True,
                                hint_text="Gemini API key (aistudio.google.com)", font_size="14sp")
        key_row.add_widget(self.key_in)

        prompt_row = BoxLayout(size_hint_y=0.13, spacing=dp(6))
        self.prompt = TextInput(multiline=False, font_size="14sp",
                                hint_text="Command or line rule (e.g. follow line slowly, search left if lost)")
        self.prompt.bind(on_text_validate=lambda *_: self._plan())
        self.mic_btn = _button("MIC", self._mic, size_hint_x=None, width=dp(58))
        self.plan_btn = _button("PLAN", self._plan, size_hint_x=None, width=dp(66))
        self.line_ai_btn = _button("LINE AI", self._line_plan, size_hint_x=None, width=dp(76))
        for w in (self.prompt, self.mic_btn, self.plan_btn, self.line_ai_btn):
            prompt_row.add_widget(w)

        self.status = Label(text="Use PLAN for steps or LINE AI for line follow/search", font_size="13sp", size_hint_y=0.08)
        self.summary = _wrap_label("", font_size="13sp", size_hint_y=0.40)

        buttons = BoxLayout(size_hint_y=0.14, spacing=dp(6))
        self.run_btn = _button("RUN / APPLY", self._run)
        self.save_btn = _button("SAVE", self._save)
        self.run_btn.disabled = True
        self.save_btn.disabled = True
        buttons.add_widget(self.run_btn)
        buttons.add_widget(self.save_btn)
        buttons.add_widget(_button("STOP", self.panel.stop_program))
        buttons.add_widget(_button("CLOSE", self.dismiss))

        for w in (key_row, prompt_row, self.status, self.summary, buttons):
            body.add_widget(w)

    def _post(self, func):
        Clock.schedule_once(lambda dt: func(), 0)

    def _set_events(self, events):
        self.events = events
        self.line_cfg = None
        ok = bool(events)
        self.run_btn.disabled = not ok
        self.save_btn.disabled = not ok

    def _set_line_cfg(self, cfg):
        self.line_cfg = cfg
        self.events = None
        self.run_btn.disabled = cfg is None
        self.save_btn.disabled = True

    def _mic(self):
        if self.panel.ai_listen(self._on_heard):
            self.status.text = "AI: listening... speak now"

    def _on_heard(self, text):
        self.prompt.text = text
        self._plan()

    def _prepare_req(self):
        key = self.key_in.text.strip()
        text = self.prompt.text.strip()
        if not key:
            self.status.text = "AI: enter the API key first"
            return None
        if not text:
            self.status.text = "AI: type or say a command"
            return None
        self.panel.api_key = key
        self.panel.save()
        self.summary.text = ""
        self.status.text = "AI: thinking..."
        self.plan_btn.disabled = True
        self.line_ai_btn.disabled = True
        return key, text

    def _plan(self):
        req = self._prepare_req()
        if not req:
            return
        self._set_events(None)
        threading.Thread(target=self._worker_plan, args=req, daemon=True).start()

    def _line_plan(self):
        req = self._prepare_req()
        if not req:
            return
        self._set_line_cfg(None)
        threading.Thread(target=self._worker_line, args=req, daemon=True).start()

    def _worker_plan(self, key, text):
        try:
            result = ai.make_plan(key, text, self.panel.gemini_models)
        except ai.AIError as exc:
            self._post(lambda m=str(exc): self._failed(m))
        except Exception as exc:
            self._post(lambda m=f"AI: {exc}": self._failed(m))
        else:
            self._post(lambda r=result: self._done_plan(r))

    def _worker_line(self, key, text):
        try:
            cfg = ai.make_line_config(key, text, self.panel.gemini_models)
        except ai.AIError as exc:
            self._post(lambda m=str(exc): self._failed(m))
        except Exception as exc:
            self._post(lambda m=f"AI: {exc}": self._failed(m))
        else:
            self._post(lambda c=cfg: self._done_line(c))

    def _failed(self, message):
        self.plan_btn.disabled = False
        self.line_ai_btn.disabled = False
        self.status.text = message
        if "no internet" in message:
            self.summary.text = "Check internet/hotspot connection and try again."

    def _done_plan(self, result):
        self.plan_btn.disabled = False
        self.line_ai_btn.disabled = False
        self._set_events(result.events)
        lines = []
        if result.note:
            lines.append(f"AI note: {result.note}")
        lines += [f"! {w}" for w in result.warnings]
        if result.events:
            self.status.text = "Plan ready. Press RUN / APPLY"
            lines.append(summarize(result.events, limit=8))
        else:
            self.status.text = "AI: no usable plan"
        self.summary.text = "\n".join(lines)

    def _done_line(self, cfg):
        self.plan_btn.disabled = False
        self.line_ai_btn.disabled = False
        self._set_line_cfg(cfg)
        self.status.text = "Line AI config ready. Press RUN / APPLY"
        self.summary.text = (
            f"Speed: {cfg.speed}/255\n"
            f"Turn ratio: {cfg.turn_ratio:.2f}\n"
            f"Lost-line search: {cfg.search_dir} ({cfg.search_sec}s)\n"
            + (f"Note: {cfg.note}" if cfg.note else "")
        )

    def _run(self):
        if self.events:
            ev = self.events
            self.dismiss()
            self.panel.run_events(ev)
        elif self.line_cfg is not None:
            cfg = self.line_cfg
            self.dismiss()
            self.panel.apply_ai_line_config(cfg)

    def _save(self):
        if self.events:
            name = self.panel.library.add("AI", self.events, "ai")
            self.status.text = f"Saved as {name}"
