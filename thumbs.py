# SPDX-License-Identifier: AGPL-3.0-only
"""Background page rendering for the preview and the page-list thumbnails.

One worker thread makes every PDFium call, so the UI never waits for a slow
page (large CAD drawings can take more than a second). Preview jobs go before
thumbnail jobs. pypdf readers are only touched on the UI thread; the worker
gets plain bytes.
"""
import atexit
from collections import OrderedDict, deque
from io import BytesIO
from itertools import count
import math
import queue
import threading
import tkinter as tk
from PIL import Image, ImageDraw, ImageTk
from pypdf import PdfWriter
import pypdfium2 as pdfium

PDFIUM_LOCK = threading.RLock()
PREVIEW, THUMBNAIL = 0, 1  # job priorities, lower runs first
IN_FLIGHT = 2
IDLE_CLOSE_SECONDS = 2
_tokens = count(1)
_worker = None


def reader_token(reader):
    """A per-reader number that, unlike id(), is never reused."""
    token = getattr(reader, '_moa_token', None)
    if token is None:
        token = reader._moa_token = next(_tokens)
    return token


def entry_key(entry):
    return (reader_token(entry['reader']), entry['page'], entry['rotation'])


def entry_source(entry):
    """PDF bytes, page index and extra rotation that pdfium can render directly."""
    reader = entry['reader']
    if not reader.is_encrypted:
        return reader.stream.getvalue(), entry['page'], entry['rotation']
    # Decrypted pages are written out so the worker never needs the password.
    with PdfWriter() as writer:
        writer.add_page(reader.pages[entry['page']])
        writer.pages[0].rotate(entry['rotation'])
        stream = BytesIO()
        writer.write(stream)
    return stream.getvalue(), 0, 0


def render_fit(document, index, rotation, width, height, zoom=None, limit=16000000):
    """Render a page to fit width x height, or at zoom. Returns (RGB image, scale)."""
    page = document[index]
    try:
        pw, ph = page.get_size()
        if rotation % 180:
            pw, ph = ph, pw
        scale = zoom if zoom is not None else max(0.01, min(width / pw, height / ph))
        scale = min(scale, math.sqrt(limit / (pw * ph)), 8000 / max(pw, ph))
        bitmap = page.render(scale=scale, rotation=rotation)
        try:
            return bitmap.to_pil().convert('RGB'), scale
        finally:
            bitmap.close()
    finally:
        page.close()


class RenderWorker:
    """The only thread that calls PDFium."""
    def __init__(self):
        self.jobs = queue.PriorityQueue()
        self.sequence = count()
        self.documents = OrderedDict()  # id(data) -> (data, PdfDocument), worker thread only
        threading.Thread(target=self.run, name='pdfium-render', daemon=True).start()

    def close_documents(self):
        with PDFIUM_LOCK:
            while self.documents:
                self.documents.popitem()[1][1].close()

    def submit(self, priority, source, width, height, zoom, reply, tag, wanted=None):
        """Render source=(bytes, index, rotation); reply gets (tag, image or None, scale).

        wanted(tag) is checked just before rendering; a job that is no longer
        wanted (an older preview request) is skipped without a reply.
        """
        self.jobs.put((priority, next(self.sequence), source, width, height, zoom, reply, tag, wanted))

    def run(self):
        documents = self.documents
        while True:
            try:
                _, _, (data, index, rotation), width, height, zoom, reply, tag, wanted = self.jobs.get(timeout=IDLE_CLOSE_SECONDS)
            except queue.Empty:
                # Idle: let go of PDFs so removed files do not stay in memory.
                if documents:
                    self.close_documents()
                continue
            if wanted is not None and not wanted(tag):
                continue
            image = scale = None
            try:
                with PDFIUM_LOCK:
                    if id(data) not in documents:
                        documents[id(data)] = (data, pdfium.PdfDocument(data))
                        while len(documents) > 4:
                            documents.popitem(last=False)[1][1].close()
                    documents.move_to_end(id(data))
                    image, scale = render_fit(documents[id(data)][1], index, rotation, width, height, zoom)
            except Exception:
                image = scale = None
            reply.put((tag, image, scale))


def worker():
    global _worker
    if _worker is None:
        _worker = RenderWorker()
    return _worker


@atexit.register
def _shutdown():
    """pypdfium2 frees PDFium in its own exit handler. Exit handlers run in
    reverse order, so this runs first: it waits for a render in progress,
    keeps the lock so no new one starts, and closes the open documents."""
    PDFIUM_LOCK.acquire()
    if _worker is not None:
        _worker.close_documents()


class Thumbnails:
    def __init__(self, widget, box, on_ready):
        self.widget = widget
        self.box = box  # (width, height) of the thumbnail cell in pixels
        self.on_ready = on_ready
        self.images = {}  # key -> PhotoImage
        self.order = deque()  # (key, entry) still to render, most wanted first
        self.in_flight = 0
        self.poll_job = None
        self.closed = False
        self.results = queue.Queue()
        self.placeholder = self.framed(None)
        widget.bind('<Destroy>', self.cleanup, add='+')

    def cleanup(self, event):
        if event.widget is self.widget:
            self.close()

    def close(self):
        """Stop delivering thumbnails (the list switched to a new thumbnail size)."""
        self.closed = True
        self.order.clear()
        if self.poll_job:
            self.widget.after_cancel(self.poll_job)
            self.poll_job = None

    def image(self, entry):
        return self.images.get(entry_key(entry), self.placeholder)

    def request(self, entries):
        """Render missing thumbnails, in the given priority order (UI thread)."""
        if self.closed:
            return
        keyed = [(entry_key(e), e) for e in entries]
        wanted = {key for key, _ in keyed}
        if len(self.images) > 2 * len(wanted) + 200:
            for key in [k for k in self.images if k not in wanted]:
                del self.images[key]
        seen = set()
        self.order = deque()
        for key, entry in keyed:
            if key not in self.images and key not in seen:
                seen.add(key)
                self.order.append((key, entry))
        self.dispatch()

    def dispatch(self):
        width, height = self.box
        while self.in_flight < IN_FLIGHT and self.order:
            key, entry = self.order.popleft()
            if key in self.images:
                continue
            try:
                source = entry_source(entry)
            except Exception:
                self.store(key, None)
                continue
            self.in_flight += 1
            # Render at twice the cell size and shrink for a sharper thumbnail.
            worker().submit(THUMBNAIL, source, (width - 4) * 2, (height - 4) * 2, None, self.results, key)
        # Poll only while the worker has something to send back.
        if self.in_flight and self.poll_job is None:
            self.poll_job = self.widget.after(40, self.poll)

    def store(self, key, image):
        self.images[key] = self.framed(image, failed=image is None)
        self.on_ready(key, self.images[key])

    def framed(self, image, failed=False):
        width, height = self.box
        canvas = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        if image is None:
            w, h = int((height - 4) * 0.72), height - 4
            page = Image.new('RGB', (w, h), '#fdecec' if failed else '#f1f4f8')
        else:
            image.thumbnail((width - 4, height - 4), Image.LANCZOS)
            page = image
        x, y = (width - page.width) // 2, (height - page.height) // 2
        canvas.paste(page, (x, y))
        ImageDraw.Draw(canvas).rectangle((x - 1, y - 1, x + page.width, y + page.height), outline='#c3cad6')
        return ImageTk.PhotoImage(canvas, master=self.widget)

    def poll(self):
        self.poll_job = None
        try:
            if self.closed or not self.widget.winfo_exists():
                return
            while True:
                try:
                    key, image, _ = self.results.get_nowait()
                except queue.Empty:
                    break
                self.in_flight -= 1
                self.store(key, image)
            self.dispatch()
        except tk.TclError:
            pass
