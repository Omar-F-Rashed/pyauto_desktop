# Updated import to point to the new 'functions.py' inside the package
from . import functions as pyauto_desktop
from PyQt6.QtCore import QThread, pyqtSignal
import traceback


class DetectionWorker(QThread):
    """
    One-shot thread for image recognition.
    Accepts a 'Haystack' image to search within, ensuring
    consistent coordinate mapping regardless of screen configuration.
    """
    result_signal = pyqtSignal(list, int)  # list of rects, count

    def __init__(self, template_img, haystack_img, confidence, grayscale, overlap_threshold=0.5):
        super().__init__()
        self.template_img = template_img
        self.haystack_img = haystack_img
        self.confidence = confidence
        self.grayscale = grayscale
        self.overlap_threshold = overlap_threshold

    def run(self):
        try:
            # We use locateAll(needle, haystack)
            # This searches purely within the image data provided,
            # avoiding any OS-level screen coordinate ambiguity.
            rects = pyauto_desktop.locateAll(
                needleImage=self.template_img,
                haystackImage=self.haystack_img,
                grayscale=self.grayscale,
                confidence=self.confidence,
                overlap_threshold=self.overlap_threshold
            )

            # Result rects are (x, y, w, h) relative to the Haystack Image (Physical Pixels)
            final_rects = list(rects)
            self.result_signal.emit(final_rects, len(final_rects))

        except Exception as e:
            print(f"Error in detection worker: {e}")
            traceback.print_exc()
            self.result_signal.emit([], 0)