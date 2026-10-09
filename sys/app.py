from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import string
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

SYS = Path(__file__).resolve().parent
ROOT = SYS.parent
CONFIG = ROOT / 'config.json'
BG, PANEL, TEXT, MUTED, ACCENT = '#101114', '#1b1d23', '#f1f2f5', '#a1a6b3', '#ffd33d'
MODES = {'Слушает': 'LISTENING', 'Играет': 'PLAYING', 'Смотрит': 'WATCHING'}


def command(action):
    result = subprocess.run(
        ['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive',
         '-ExecutionPolicy', 'Bypass', '-File', str(SYS / 'control.ps1'), '-Action', action],
        capture_output=True, encoding='utf-8', errors='replace',
        creationflags=subprocess.CREATE_NO_WINDOW, timeout=90, cwd=ROOT,
    )
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout or 'Команда завершилась с ошибкой').strip())
    return result.stdout.strip()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Yandex Music · Discord Presence')
        self.geometry('1040x820')
        self.minsize(960, 700)
        self.configure(bg=BG)
        config_source = CONFIG if CONFIG.exists() else ROOT / 'config.example.json'
        self.config_data = json.loads(config_source.read_text(encoding='utf-8-sig'))
        self.messages = queue.Queue()
        self.busy = False
        self.task_running = None
        self.autostart = False
        self.last_poll = 0
        self.vars = {}
        self.buttons = []
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('.', background=PANEL, foreground=TEXT, font=('Segoe UI', 10))
        style.configure('TFrame', background=PANEL)
        style.configure('TLabel', background=PANEL)
        style.configure('TButton', padding=(12, 9), background='#30343e', foreground=TEXT)
        style.map('TButton', background=[('active', '#454b59')])
        style.configure('Accent.TButton', background=ACCENT, foreground='#161616')
        style.map('Accent.TButton', background=[('active', '#ffe471')])
        style.configure('TEntry', fieldbackground='#292c34', foreground=TEXT, padding=7)
        style.configure('TCombobox', fieldbackground='#292c34', foreground=TEXT, padding=6)
        style.map('TCombobox', fieldbackground=[('readonly', '#292c34')], foreground=[('readonly', TEXT)])
        style.configure('TCheckbutton', background=PANEL, foreground=TEXT, padding=5)
        style.map('TCheckbutton', background=[('active', PANEL)])
        style.configure('TNotebook', background=BG, borderwidth=0)
        style.configure('TNotebook.Tab', padding=(18, 10), background='#292c34')
        style.map('TNotebook.Tab', background=[('selected', PANEL)])
        header = tk.Frame(self, bg=BG)
        header.pack(fill='x', padx=26, pady=(22, 14))
        tk.Label(header, text='Музыка в Discord', bg=BG, fg=TEXT,
                 font=('Segoe UI Semibold', 24)).pack(anchor='w')
        tk.Label(header, text='Управление интеграцией и видом статуса', bg=BG,
                 fg=MUTED, font=('Segoe UI', 11)).pack(anchor='w', pady=(5, 0))
        body = tk.Frame(self, bg=BG)
        body.pack(fill='both', expand=True, padx=26)
        left = ttk.Frame(body, padding=20)
        left.pack(side='left', fill='both', expand=True, padx=(0, 16))
        right = ttk.Frame(body, padding=20, width=350)
        right.pack(side='right', fill='both')
        right.pack_propagate(False)
        notebook = ttk.Notebook(left)
        notebook.pack(fill='both', expand=True)
        appearance, settings, logs = (ttk.Frame(notebook, padding=(6, 16)) for _ in range(3))
        notebook.add(appearance, text='Вид статуса')
        notebook.add(settings, text='Подключение')
        notebook.add(logs, text='Журнал')
        self.field(appearance, 'Первая строка', 'details_template', '{title}')
        self.field(appearance, 'Вторая строка', 'state_template', '{artist}')
        ttk.Label(appearance, text='Подстановки: {title} — трек, {artist} — исполнитель,\n{album} — альбом', foreground=MUTED).pack(anchor='w', pady=(0, 10))
        ttk.Label(appearance, text='Тип активности').pack(anchor='w')
        mode = next((k for k, v in MODES.items() if v == self.config_data.get('activity_type', 'LISTENING')), 'Слушает')
        self.mode = tk.StringVar(value=mode)
        ttk.Combobox(appearance, values=list(MODES), textvariable=self.mode, state='readonly').pack(fill='x', pady=(5, 10))
        self.mode.trace_add('write', self.preview)
        self.check(appearance, 'Показывать обложку', 'show_cover', True)
        self.check(appearance, 'Показывать время воспроизведения', 'show_timing', True)
        self.check(appearance, 'Кнопка перехода к текущему треку', 'show_button', True)
        self.check(appearance, 'Ссылка на названии трека', 'link_title', True)
        self.check(appearance, 'Скрывать статус сразу при паузе', 'clear_when_paused', False)
        self.field(appearance, 'Текст кнопки', 'button_label', 'Открыть трек')
        self.field(settings, 'Discord Application ID', 'discord_application_id', '')
        self.field(settings, 'Запасная обложка (имя asset в Discord)', 'fallback_image_asset', 'yandex_music')
        self.check(settings, 'Искать обложку и ссылку в Яндекс Музыке', 'find_cover_online', True)
        self.check(settings, 'Отключать RPC после 5 минут неизменной паузы', 'hide_after_pause', True)
        self.field(settings, 'Проверять воспроизведение каждые N секунд', 'poll_seconds', 2)
        ttk.Label(settings, text='Название приложения в заголовке Discord задаётся\nв Developer Portal. Остальные параметры сохранены\nв config.json.', foreground=MUTED).pack(anchor='w', pady=14)
        self.log_text = tk.Text(logs, bg=BG, fg=TEXT, relief='flat', font=('Consolas', 9), wrap='word')
        self.log_text.pack(fill='both', expand=True)
        ttk.Button(logs, text='Обновить журнал', command=self.read_log).pack(anchor='w', pady=(10, 0))
        ttk.Button(left, text='Сохранить и применить', style='Accent.TButton', command=self.save).pack(fill='x', pady=(16, 0))
        ttk.Label(right, text='Состояние', font=('Segoe UI Semibold', 15)).pack(anchor='w')
        self.process_label = ttk.Label(right, text='Проверяю процесс…', foreground=MUTED)
        self.process_label.pack(anchor='w', pady=(12, 5))
        self.discord_label = ttk.Label(right, text='Discord: проверяю…', foreground=MUTED)
        self.discord_label.pack(anchor='w', pady=(0, 16))
        row = ttk.Frame(right)
        row.pack(fill='x')
        for text, action in [('Запустить', 'start'), ('Остановить', 'stop')]:
            b = ttk.Button(row, text=text, command=lambda a=action: self.run_action(a))
            b.pack(side='left', expand=True, fill='x', padx=(0, 5))
            self.buttons.append(b)
        b = ttk.Button(right, text='Перезапустить', command=lambda: self.run_action('restart'))
        b.pack(fill='x', pady=8)
        self.buttons.append(b)
        self.auto_button = ttk.Button(right, text='Проверяю автозапуск…', command=self.toggle_auto)
        self.auto_button.pack(fill='x')
        self.buttons.append(self.auto_button)
        ttk.Separator(right).pack(fill='x', pady=22)
        ttk.Label(right, text='Предпросмотр', font=('Segoe UI Semibold', 15)).pack(anchor='w')
        ttk.Label(right, text='Пример оформления; вид в Discord может отличаться.', wraplength=305, foreground=MUTED).pack(anchor='w', pady=(6, 14))
        card = tk.Frame(right, bg=BG, padx=16, pady=16)
        card.pack(fill='x')
        self.preview_heading = tk.Label(card, bg=BG, fg=MUTED, anchor='w', font=('Segoe UI', 10))
        self.preview_heading.pack(fill='x')
        self.cover = tk.Label(card, text='♫', bg='#30343e', fg=ACCENT, font=('Segoe UI', 28), width=4)
        self.cover.pack(anchor='w', pady=(12, 10))
        self.preview_title = tk.Label(card, bg=BG, fg=TEXT, anchor='w', justify='left', wraplength=270, font=('Segoe UI Semibold', 12))
        self.preview_title.pack(fill='x')
        self.preview_artist = tk.Label(card, bg=BG, fg=MUTED, anchor='w', justify='left', wraplength=270)
        self.preview_artist.pack(fill='x', pady=5)
        self.preview_time = tk.Label(card, bg=BG, fg=TEXT, anchor='w')
        self.preview_time.pack(fill='x', pady=6)
        self.preview_button = tk.Label(card, bg='#30343e', fg=TEXT, pady=9)
        self.preview_button.pack(fill='x', pady=(8, 0))
        self.now_label = ttk.Label(right, text='', wraplength=300, foreground=MUTED)
        self.now_label.pack(anchor='w', pady=14)
        self.notice = tk.StringVar(value='Закрытие окна оставляет интеграцию работать в фоне.')
        tk.Label(self, textvariable=self.notice, bg=BG, fg=MUTED, anchor='w', wraplength=980).pack(fill='x', padx=26, pady=16)
        self.preview()
        self.read_log()
        self.after(100, self.tick)

    def field(self, parent, label, key, default):
        ttk.Label(parent, text=label).pack(anchor='w')
        var = tk.StringVar(value=str(self.config_data.get(key, default)))
        self.vars[key] = var
        ttk.Entry(parent, textvariable=var).pack(fill='x', pady=(5, 10))
        var.trace_add('write', self.preview)

    def check(self, parent, label, key, default):
        var = tk.BooleanVar(value=self.config_data.get(key, default))
        self.vars[key] = var
        ttk.Checkbutton(parent, text=label, variable=var).pack(anchor='w')
        var.trace_add('write', self.preview)

    def preview(self, *_):
        if not hasattr(self, 'preview_title'):
            return
        data = self.live_data()
        values = {'title': data.get('title') or 'Название трека', 'artist': data.get('artist') or 'Исполнитель', 'album': data.get('album') or 'Название альбома'}
        try:
            title = self.vars['details_template'].get().format_map(values)
            artist = self.vars['state_template'].get().format_map(values)
        except (ValueError, KeyError, AttributeError, IndexError):
            title, artist = 'Проверьте шаблон строки', '{title}, {artist}, {album}'
        paused = bool(data.get('title')) and not data.get('playing')
        if paused:
            artist += ' • Пауза'
        hidden = paused and (self.vars['clear_when_paused'].get() or (data.get('pause_timed_out') and self.vars['hide_after_pause'].get()))
        self.preview_heading.config(text='Статус скрыт на паузе' if hidden else self.mode.get() + ' Yandex Music')
        self.preview_title.config(text=title[:128] if not hidden else '')
        self.preview_artist.config(text=artist[:128] if not hidden else '')
        if self.vars['show_cover'].get() and not hidden:
            if not self.cover.winfo_manager(): self.cover.pack(after=self.preview_heading, anchor='w', pady=(12, 10))
        else: self.cover.pack_forget()
        self.preview_time.config(text='01:19 ━━━━━━━━ 04:15' if self.vars['show_timing'].get() and not paused and not hidden else '')
        if self.vars['show_button'].get() and not hidden:
            self.preview_button.config(text=self.vars['button_label'].get())
            if not self.preview_button.winfo_manager(): self.preview_button.pack(fill='x', pady=(8, 0))
        else: self.preview_button.pack_forget()

    def live_data(self):
        try:
            data = json.loads((SYS / 'status.json').read_text(encoding='utf-8'))
            if self.task_running is False or time.time() - data['updated'] > 12:
                return {}
            return data
        except (OSError, ValueError, KeyError): return {}

    def worker(self, fn, kind):
        if self.busy: return
        self.busy = True
        for b in self.buttons: b.state(['disabled'])
        def work():
            try: self.messages.put((kind, fn(), None))
            except Exception as exc: self.messages.put((kind, None, str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def run_action(self, action):
        self.notice.set('Выполняю действие…')
        self.worker(lambda: command(action), 'action')

    def toggle_auto(self):
        self.run_action('disable' if self.autostart else 'enable')

    def save(self):
        if self.busy:
            self.notice.set('Дождитесь завершения текущего действия.')
            return
        try:
            data = dict(self.config_data)
            data.update({key: var.get() for key, var in self.vars.items()})
            data['discord_application_id'] = data['discord_application_id'].strip()
            if not data['discord_application_id'].isascii() or not data['discord_application_id'].isdigit():
                raise ValueError('Application ID должен состоять из цифр.')
            data['poll_seconds'] = float(data['poll_seconds'])
            if not 1 <= data['poll_seconds'] <= 60:
                raise ValueError('Период проверки: от 1 до 60 секунд.')
            if not 1 <= len(data['button_label'].strip()) <= 32:
                raise ValueError('Текст кнопки: от 1 до 32 символов.')
            data['button_label'] = data['button_label'].strip()
            for key in ('details_template', 'state_template'):
                if not data[key].strip() or len(data[key]) > 128:
                    raise ValueError('Строка статуса: от 1 до 128 символов.')
                for _, field, spec, conversion in string.Formatter().parse(data[key]):
                    if field is not None and (field not in ('title', 'artist', 'album') or spec or conversion):
                        raise ValueError('Используйте только {title}, {artist} и {album}.')
            data['activity_type'] = MODES[self.mode.get()]
            def apply():
                state = json.loads(command('status'))
                tmp = CONFIG.with_suffix('.tmp')
                tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
                tmp.replace(CONFIG)
                self.config_data = data
                if state['running']:
                    command('restart')
                    return 'Настройки сохранены и применены.'
                return 'Настройки сохранены. Они применятся при запуске интеграции.'
            self.notice.set('Сохраняю настройки…')
            self.worker(apply, 'action')
        except (ValueError, TypeError) as exc:
            messagebox.showerror('Проверьте настройки', str(exc), parent=self)

    def read_log(self):
        try: content = '\n'.join((SYS / 'presence.log').read_text(encoding='utf-8', errors='replace').splitlines()[-80:])
        except OSError: content = 'Журнал пока пуст.'
        self.log_text.config(state='normal')
        self.log_text.delete('1.0', 'end')
        self.log_text.insert('end', content)
        self.log_text.see('end')
        self.log_text.config(state='disabled')

    def tick(self):
        while not self.messages.empty():
            kind, result, error = self.messages.get_nowait()
            self.busy = False
            for b in self.buttons: b.state(['!disabled'])
            if error:
                self.notice.set('Ошибка: ' + error[:220])
                if kind != 'status': messagebox.showerror('Не удалось выполнить действие', error, parent=self)
            elif kind == 'status':
                self.task_running, self.autostart = result['running'], result['autostart']
                self.process_label.config(text='● Процесс работает' if self.task_running else '○ Процесс остановлен', foreground='#6ddd9b' if self.task_running else MUTED)
                self.auto_button.config(text='Выключить автозапуск' if self.autostart else 'Включить автозапуск')
            else:
                self.notice.set(result)
                self.last_poll = 0
                self.read_log()
        live = self.live_data()
        self.discord_label.config(text='Discord: отключён после 5 минут паузы' if live.get('pause_timed_out') else ('Discord: подключён' if live.get('connected') else ('Discord: ожидаю Яндекс Музыку / Discord' if self.task_running else 'Discord: интеграция выключена')))
        self.now_label.config(text=('Сейчас: ' + live.get('artist', '') + ' — ' + live['title']) if live.get('title') else 'Ожидание Яндекс Музыки')
        self.preview()
        if not self.busy and time.monotonic() - self.last_poll > 5:
            self.last_poll = time.monotonic()
            self.worker(lambda: json.loads(command('status')), 'status')
        self.after(400, self.tick)


if __name__ == '__main__':
    try:
        App().mainloop()
    except Exception as exc:
        import ctypes
        (SYS / 'app-error.log').write_text(str(exc), encoding='utf-8')
        ctypes.windll.user32.MessageBoxW(0, str(exc), 'Ошибка запуска Yandex Presence', 0x10)
