"""Authoritative row state and monotonic replacement events."""
import base64
import io
import uuid
import numpy as np
from PIL import Image


class ImageState:
    def __init__(self, emit, mode, width, height, source, confidence, beginning_known):
        self.emit = emit
        self.id = uuid.uuid4().hex
        self.mode = mode
        self.width = width
        self.height = height
        self.beginning_known = beginning_known
        self.rows = {}
        self.revisions = {}
        self.flags = {}
        emit(dict(type="image_start", image_id=self.id, mode=mode, width=width,
                  nominal_height=height, acquisition_source=source,
                  acquisition_confidence=confidence, beginning_known=beginning_known,
                  transmitter_row_numbering_known=beginning_known))

    def row(self, index, rgb, confidence, flags, reason=None, **metadata):
        if not 0 <= index < self.height or rgb.shape != (self.width, 3):
            raise ValueError("invalid output row")
        revision = self.revisions.get(index, -1) + 1
        self.rows[index] = rgb.copy()
        self.revisions[index] = revision
        self.flags[index] = list(flags)
        event = dict(type="row" if revision == 0 else "row_revision", image_id=self.id,
                     row_index=index, width=self.width, revision=revision,
                     rgb=base64.b64encode(rgb.tobytes()).decode("ascii"),
                     row_confidence=float(confidence), quality_flags=list(flags), **metadata)
        if revision:
            event["reason"] = reason or "adjacent_chroma_received"
        self.emit(event)

    def quality_fields(self):
        flags = self.flags
        confirmed = sum(not any(flag in value for flag in ("timing_recovered", "missing", "timing_unverified"))
                        for value in flags.values())
        unverified = sum("timing_unverified" in value for value in flags.values())
        longest = run = 0
        previous = None
        for row, value in sorted(flags.items()):
            run = (run + 1 if previous == row - 1 else 1) if "timing_unverified" in value else 0
            longest = max(longest, run)
            previous = row
        missing = any("missing" in value for value in flags.values())
        low_quality = any("low_signal_quality" in value for value in flags.values())
        quality = ("unsynchronized" if flags and (not confirmed or unverified > confirmed)
                   else "degraded" if missing or unverified or low_quality else "good")
        return dict(decode_quality=quality, sync_confirmed_row_count=confirmed,
                    unverified_row_count=unverified, longest_unverified_run=longest)

    def finish(self, reason, status):
        if not self.rows:
            # There is no picture to encode; avoid a height-0 / height-1 PNG mismatch.
            return
        actual_height = max(self.rows) + 1
        quality = self.quality_fields()
        missing = sum("missing" in self.flags[i] for i in self.rows)
        kind = ("image_complete" if self.beginning_known and len(self.rows) == self.height
                and not missing and not quality["unverified_row_count"] else "image_partial")
        canvas = np.zeros((actual_height, self.width, 3), np.uint8)
        for y, pixels in self.rows.items():
            canvas[y] = pixels
        data = io.BytesIO()
        Image.fromarray(canvas).save(data, format="PNG")
        recovered = sum("timing_recovered" in self.flags[i] for i in self.rows)
        status = dict(status, **quality)
        summary = dict(quality, flagged_rows=sum(bool(v) for v in self.flags.values()))
        if "tracking_status" in status:
            summary["tracking_status"] = status["tracking_status"]
        self.emit(dict(status, type=kind, image_id=self.id, mode=self.mode, completion_reason=reason,
                       beginning_known=self.beginning_known,
                       transmitter_row_numbering_known=self.beginning_known,
                       decoded_row_count=len(self.rows)-missing, output_row_count=len(self.rows),
                       missing_row_count=missing, recovered_row_count=recovered,
                       unknown_tail_rows=self.height-actual_height if self.beginning_known else None,
                       width=self.width, height=actual_height,
                       png=base64.b64encode(data.getvalue()).decode("ascii"),
                       quality_summary=summary))
