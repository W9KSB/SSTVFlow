"""Streaming coordinator, Robot 36 extraction, controls and quality events."""
from collections import deque
import math
import numpy as np
from scipy.ndimage import median_filter
from .dsp import Demodulator, FrequencyBuffer
from .protocol import ProtocolDetector
from .timing import LineClock
from .image import ImageState
from .color import frequency_to_byte, ycrcb_to_rgb, display_adjust, guided_chroma_noise_reduction
from . import __version__
from . import pd120
from .pixels import fit_pixel_frequencies, adaptive_channel_noise_reduction
from .sync import matched_sync, robot_chroma_phase, reference_noise_ratio, robot_porch_matches, fit_reference_offset


class Decoder:
    block_samples = 512

    def __init__(self, rate, emit, method="quadrature", diagnostics=None, pixel_estimator="adaptive"):
        if not 8000 <= rate <= 192000:
            raise ValueError("sample rate must be between 8000 and 192000 Hz")
        self.rate = int(rate)
        self.emit = emit
        self.method = method
        self.diagnostics = diagnostics
        if pixel_estimator not in ("phase", "adaptive", "sinefit"):
            raise ValueError("pixel estimator must be phase, adaptive or sinefit")
        self.pixel_estimator = pixel_estimator
        self.fit_channels = 0
        self.total_pcm_sum = 0.0
        self.total_pcm_count = 0
        self.samples = 0
        self.pending = bytearray()
        self.closed = False
        self.draining = False
        self.image = None
        self.clock = None
        self.forced = None
        self.auto_frequency = True
        self.manual_frequency = 0.0
        self.measured_frequency = 0.0
        self.frequency_confidence = 0.0
        self.frequency_source = None
        self.auto_slant = True
        self.manual_ppm = 0.0
        self.horizontal_ms = 0.0
        self.impulse_rejection = False
        self.noise_reduction = 0.0
        self.auto_noise_reduction = True
        self.noise_reference_ratio = None
        self.noise_reduced_channels = 0
        self.display = dict(brightness=0.0, contrast=1.0, gamma=1.0, saturation=1.0)
        self.last_quality = 0
        self.level = 0.0
        self.clipped = False
        self.silence_samples = 0
        self.dc_sum = 0.0
        self.monitor_samples = 0
        self.impulses = 0
        self.input_noise = None
        self._pipeline()
        emit(dict(type="ready", sample_rate=rate, supported_modes=["Robot36", "PD120"],
                  decoder_version=__version__, development_stage="quality_validation",
                  demodulator=method, control_interface="newline JSON on --control-fd",
                  pixel_estimator=pixel_estimator,
                  auto_noise_reduction=self.auto_noise_reduction,
                  dsp_delay_samples=self.dsp.delay + .5))

    def _pipeline(self):
        self.dsp = Demodulator(self.rate, self.method)
        self.history = FrequencyBuffer(self.rate)
        # Protocol references benefit from narrower filtering; picture extraction
        # keeps the broader path available for detail. Both timelines are explicit.
        self.protocol_dsp=Demodulator(self.rate,"narrow") if self.method!="narrow" else None
        self.protocol_history=FrequencyBuffer(self.rate) if self.protocol_dsp else self.history
        self.pixel_history=self.history
        self.active_pixel_band=self.method
        self.initial_pixel_band = self.method
        self.pixel_band_errors = deque(maxlen=3)
        self.pixel_band_clean_lines = 0
        self.raw_history = FrequencyBuffer(self.rate)
        self.detector = ProtocolDetector(self.rate, self.protocol_history, self._header, self._sync)
        self.detector.offset = self.applied_frequency
        self.detector.next_bin = self.samples
        self.candidates = deque(maxlen=32)
        self.observed_lines = {}
        self.components = {}
        self.next_line = 0
        self.last_sync = self.samples
        self.sync_gap = 0
        self.pd_channels = None
        self.noise_reference_ratio = None
        self.reference_offsets = deque(maxlen=16)

    @property
    def applied_frequency(self):
        return self.measured_frequency if self.auto_frequency else self.manual_frequency

    def feed(self, data):
        if self.closed:
            raise RuntimeError("decoder already at EOF")
        count = self.block_samples * 2
        view = memoryview(data)
        offset = 0
        while offset < len(view):
            take = min(count-len(self.pending), len(view)-offset)
            self.pending.extend(view[offset:offset+take])
            offset += take
            if len(self.pending) == count:
                block = bytes(self.pending)
                self.pending.clear()
                self._process(np.frombuffer(block, dtype="<i2").astype(float) / 32768)

    def _process(self, pcm):
        if not len(pcm):
            return
        self.level = float(np.sqrt(np.mean(pcm**2)))
        self.dc_sum += float(np.sum(pcm))
        self.monitor_samples += len(pcm)
        if not self.draining:
            self.total_pcm_sum += float(np.sum(pcm))
            self.total_pcm_count += len(pcm)
        self.raw_history.append(self.samples+np.arange(len(pcm)),pcm,np.zeros(len(pcm)))
        self.clipped = bool(np.mean(abs(pcm) >= .999) > .001)
        if self.level < .001:
            self.silence_samples += len(pcm)
        else:
            self.silence_samples = 0
        positions, frequency, amplitude = self.dsp.process(pcm, self.samples)
        if self.protocol_dsp:
            pp,pf,pa=self.protocol_dsp.process(pcm,self.samples)
            self.protocol_history.append(pp,pf,pa)
        # Envelope variations provide a rough noise indicator, never a calibrated SNR.
        median_amplitude = float(np.median(amplitude))
        self.input_noise = float(np.median(abs(amplitude-median_amplitude)) / max(median_amplitude,1e-6))
        self.impulses += int(np.sum(abs(pcm) > max(.5, self.level*5)))
        self.samples += len(pcm)
        self.history.append(positions, frequency, amplitude)
        self.detector.consume()
        self._rows()
        if self.image and self.silence_samples > self.rate * .6:
            self._finish("lost_signal")
        if self.samples - self.last_quality >= self.rate:
            self.last_quality = self.samples
            self.emit(dict(type="quality", signal_rms=self.level, clipping=self.clipped,
                           dc_offset=self.dc_sum/max(1,self.monitor_samples),
                           envelope_noise_estimate=self.input_noise, impulse_sample_count=self.impulses,
                           extremely_low_level=self.level < .001, prolonged_silence=self.silence_samples > self.rate,
                           **self.status()))
            self.dc_sum = 0.0
            self.monitor_samples = 0
            self.impulses = 0

    def _header(self, code, start, offset, confidence):
        self.emit(dict(type="acquisition", candidate_mode="Robot36" if code == 8 else "PD120",
                       acquisition_source="VIS", vis_code=code, vis_confidence=confidence,
                       confidence=confidence, frequency_offset_hz=offset, timing_confidence=0.0,
                       sample_position=start))
        mode = "Robot36" if code == 8 else "PD120"
        if self.forced and self.forced != mode:
            return
        self.measured_frequency = offset
        self.frequency_confidence = confidence
        self.frequency_source = "VIS_leader"
        self.detector.offset = self.applied_frequency
        self._start(start, "VIS", confidence, True, mode)

    def _start(self, start, source, confidence, known, mode="Robot36", reference_positions=None):
        if self.image:
            self._finish("next_image_started")
        self.image = ImageState(self.emit, mode, 320 if mode=="Robot36" else 640,
                                240 if mode=="Robot36" else 496, source, confidence, known)
        self.detector.search_offset = False
        self.detector.offset = self.applied_frequency
        self.reference_offsets.clear()
        probe = start + (-.40 if known else .002) * self.rate
        self.noise_reference_ratio = reference_noise_ratio(
            self.raw_history, self.rate, probe, 1900 if known else 1200, self.applied_frequency)
        self.pixel_history=self.history
        self.active_pixel_band=self.method
        if self.protocol_dsp:
            # Choose from protocol references, never from picture content.
            target=1900 if known else 1200
            try:
                errors = []
                for reference in reference_positions or [start]:
                    probe_start=reference-.45*self.rate if known else reference+.002*self.rate
                    probe_end=reference-.35*self.rate if known else reference+.007*self.rate
                    broad=self.history.interval(probe_start,probe_end)
                    narrow=self.protocol_history.interval(probe_start,probe_end)
                    errors.append((np.percentile(abs(broad-target-self.applied_frequency),90),
                                   np.percentile(abs(narrow-target-self.applied_frequency),90)))
                broad_error,narrow_error=np.median(errors,axis=0)
                if broad_error>120 and narrow_error<broad_error*.85:
                    self.pixel_history=self.protocol_history
                    self.active_pixel_band="narrow"
            except ValueError:
                pass
        self.pixel_band_errors.clear()
        self.pixel_band_clean_lines = 0
        self.initial_pixel_band = self.active_pixel_band
        self.physical_lines = 240 if mode=="Robot36" else 248
        self.clock = LineClock(self.rate, start, .150 if mode=="Robot36" else pd120.PAIR_SECONDS)
        self.clock.auto = self.auto_slant
        self.clock.manual_ppm = self.manual_ppm
        if not self.auto_slant:
            self.clock.period *= 1 + self.manual_ppm / 1e6
        self.next_line = 0
        self.components = {}
        self.observed_lines = {0:confidence} if known else {}
        self.last_sync = start
        self.sync_gap = 0
        self.pd_channels = None

    def _sync(self, position, duration, offset, confidence):
        mode = "Robot36" if .006<=duration<=.013 else "PD120" if .016<=duration<=.023 else None
        if mode is None or confidence < .55:
            return
        if self.image:
            if mode != self.image.mode:
                return
            line = round((position - self.clock.origin) / self.clock.period)
            if 0 <= line < self.physical_lines and self.clock.observe(line, position, confidence):
                self.observed_lines[line] = confidence
                self.last_sync = position
                if confidence > .7:
                    self._noise_reference(position)
                fitted = self._frequency_reference(position, confidence)
                if not fitted and not self.reference_offsets and self.auto_frequency and confidence > .8 and abs(offset-self.measured_frequency) < 65:
                    self.measured_frequency += .025 * (offset-self.measured_frequency)
                    self.frequency_confidence = confidence
                    self.frequency_source = "line_sync"
                    self.detector.offset = self.applied_frequency
                if self.diagnostics:
                    self.diagnostics(dict(sync_sample=position, line=line, confidence=confidence,
                                          **self.clock.status(self.next_line)))
            return
        if self.forced and self.forced != mode:
            return
        self.candidates.append((position, duration, offset, confidence))
        if len(self.candidates) >= 3:
            nominal = .150 if mode=="Robot36" else pd120.PAIR_SECONDS
            c=self.candidates[-1]
            def previous(candidate):
                choices=[v for v in self.candidates if v[0]<candidate[0] and
                         abs((candidate[0]-v[0])/self.rate-nominal)<nominal*.017 and
                         abs(v[2]-candidate[2])<50 and
                         ((.006<=v[1]<=.013) if mode=="Robot36" else (.016<=v[1]<=.023))]
                return min(choices,key=lambda v:abs((candidate[0]-v[0])/self.rate-nominal)) if choices else None
            b=previous(c)
            a=previous(b) if b is not None else None
            if a is None:
                return
            periods = np.diff([a[0], b[0], c[0]]) / self.rate
            same_kind = all((.006<=v[1]<=.013) if mode=="Robot36" else (.016<=v[1]<=.023) for v in (a,b,c))
            if same_kind and np.max(abs(periods-nominal)) < nominal*.017 and abs(periods[0]-periods[1]) < .002:
                pulse=.009 if mode=="Robot36" else .020
                a,b,c=[(self.detector._edge(v[0]+pulse*self.rate,1350+v[2],rising=True)-pulse*self.rate,
                        *v[1:]) for v in (a,b,c)]
                # Cadence alone is insufficient: check both porch and alternating separator.
                try:
                    for candidate in (a, b):
                        porch_start = .010 if mode=="Robot36" else .0206
                        porch = np.mean(self.protocol_history.interval(candidate[0]+porch_start*self.rate,
                                                             candidate[0]+(porch_start+.001)*self.rate))
                        if abs(porch-1500-candidate[2]) > 65:
                            if mode != "Robot36" or not robot_porch_matches(
                                    self.raw_history, self.rate, candidate[0], candidate[2]):
                                return
                    if mode=="Robot36":
                        separators = [np.median(self.protocol_history.interval(v[0]+.101*self.rate, v[0]+.103*self.rate))-v[2]
                                      for v in (a,b)]
                        if not ((abs(separators[0]-1500)<70 and abs(separators[1]-2300)<70) or
                                (abs(separators[0]-2300)<70 and abs(separators[1]-1500)<70)):
                            return
                    else:
                        # PD has no inter-channel marker; require video-band evidence
                        # throughout its four documented channel intervals.
                        for candidate in (a,b):
                            values=self.protocol_history.interval(candidate[0]+.023*self.rate,candidate[0]+.50*self.rate)
                            if np.mean((values-candidate[2]>1400)&(values-candidate[2]<2400))<.8:
                                return
                except ValueError:
                    return
                self.measured_frequency = float(np.median([a[2], b[2], c[2]]))
                self.frequency_confidence = min(a[3],b[3],c[3])
                self.frequency_source = "repeated_sync"
                offsets = []
                if self.auto_frequency:
                    for candidate in (a,b,c):
                        fitted = fit_reference_offset(self.raw_history, self.rate, candidate[0]+.002*self.rate,
                                                      1200, self.measured_frequency)
                        if fitted is not None:
                            offsets.append(fitted)
                    if len(offsets) >= 2:
                        self.measured_frequency = float(np.median([v[0] for v in offsets]))
                        self.frequency_source = "raw_sync_fit"
                self.emit(dict(type="acquisition", candidate_mode=mode, acquisition_source="line_structure",
                               confidence=self.frequency_confidence, frequency_offset_hz=self.applied_frequency,
                               timing_confidence=.25, sample_position=a[0], vis_code=None))
                self._start(a[0], "forced_line_structure" if self.forced else "line_structure", self.frequency_confidence,
                            False, mode, reference_positions=[a[0],b[0],c[0]])
                self.reference_offsets.extend(offsets)
                for i, v in enumerate((a,b,c)):
                    self.clock.observe(i, v[0], v[3])
                    self.observed_lines[i] = v[3]

    def _pixels(self, start, duration, count, chroma=False):
        centers = start + (np.arange(count)+.5) * duration/count
        # Short pixel aperture (not a long tone window); fractional interpolation.
        aperture = duration/count * .9
        points = max(7, math.ceil(aperture))
        offsets = (np.arange(points)+.5)/points - .5
        positions = centers[None,:] + offsets[:,None]*aperture
        if self.impulse_rejection:
            values = self.pixel_history.read(positions)
            f = np.median(values, axis=0)
        else:
            correlation = self.pixel_history.read_correlation(positions, self.rate)
            f = np.angle(np.sum(correlation, axis=0)) * self.rate / (2 * np.pi)
        amp = self.pixel_history.read(centers, True)
        valid = (amp > .0015) & (f-self.applied_frequency > 1350) & (f-self.applied_frequency < 2450)
        clean_fit = False
        if self.pixel_estimator != "phase":
            fitted=np.zeros(count)
            residual=np.ones(count)
            first=np.ceil(centers-duration/count*.40).astype(np.int64)
            last=np.floor(centers+duration/count*.40).astype(np.int64)+1
            lengths=last-first
            dc=self.total_pcm_sum/max(1,self.total_pcm_count)
            for length in np.unique(lengths):
                indices=np.flatnonzero(lengths==length)
                if length<3:
                    continue
                windows=self.raw_history.read(first[indices,None]+np.arange(length))-dc
                measured,error,_=fit_pixel_frequencies(windows,self.rate,offset_hz=self.applied_frequency)
                fitted[indices]=measured
                residual[indices]=error
            # Residual is fit quality, not frequency certainty. Only a whole clean
            # channel earns adaptive use; isolated low-residual noisy pixels do not.
            if self.pixel_estimator=="sinefit" or np.mean(residual<1e-5)>.90:
                trustworthy=(lengths>=3) & ((residual<1e-5) if self.pixel_estimator=="adaptive" else True)
                f=np.where(trustworthy,fitted,f)
                self.fit_channels+=1
                clean_fit = np.mean(residual<1e-5)>.90
        if self.auto_noise_reduction and not clean_fit and self.noise_reference_ratio is not None and self.noise_reference_ratio > .02:
            f = adaptive_channel_noise_reduction(f)
            self.noise_reduced_channels += 1
        if self.noise_reduction:
            filtered = median_filter(f, size=3, mode="nearest")
            strength=self.noise_reduction if chroma else self.noise_reduction*.35
            f = f*(1-strength) + filtered*strength
        return frequency_to_byte(f-self.applied_frequency), float(np.mean(valid))

    def _pixel_band_reference(self, start, scale):
        # An acquisition-selected narrow path remains the established image path.
        # Only images whose initial references support the wider path adapt later.
        if self.protocol_dsp is None or self.initial_pixel_band == "narrow":
            return
        try:
            begin = start + .002*self.rate*scale
            end = start + .007*self.rate*scale
            errors = tuple(float(np.percentile(abs(history.interval(begin,end)
                                                   -1200-self.applied_frequency),90))
                           for history in (self.history,self.protocol_history))
        except ValueError:
            return
        self.pixel_band_errors.append(errors)
        broad, narrow = np.median(self.pixel_band_errors,axis=0)
        # Sustained reference errors indicate fading or interference. Both FIR
        # histories use the input timeline, so a row-boundary change adds no delay.
        if len(self.pixel_band_errors) >= 3 and broad > 120 and narrow < broad*.85:
            self.pixel_history = self.protocol_history
            self.active_pixel_band = "narrow"
            self.pixel_band_clean_lines = 0
        elif errors[0] < 60:
            self.pixel_band_clean_lines += 1
            # Require a clean run before restoring the wider detail path; isolated
            # quiet sync pulses should not alternate filters on successive rows.
            if self.pixel_band_clean_lines >= 8:
                self.pixel_history = self.history
                self.active_pixel_band = self.method
        else:
            self.pixel_band_clean_lines = 0

    def _rows(self):
        if self.image and self.image.mode=="PD120":
            self._pd_rows()
            return
        while self.image:
            line = self.next_line
            start = self.clock.predict(line)
            scale = self.clock.period / (.150 * self.rate)
            required = start + self.clock.period + 2
            if self.draining:
                # Pixel centers need less audio than the next sync edge. Permit the
                # final fully received channel, without counting fabricated tail PCM.
                required = start + self.clock.period - .00005*self.rate
            if self.history.latest < required:
                break
            self._recover_sync(line,start,.009,scale)
            start=self.clock.predict(line)
            scale=self.clock.period/(.150*self.rate)
            self._pixel_band_reference(start,scale)
            inferred = line not in self.observed_lines
            self.sync_gap = self.sync_gap + 1 if inferred else 0
            if self.sync_gap > (32 if self.clock.confidence >= .7 else 8):
                self._finish("unrecoverable_sync_loss")
                break
            phase = self.horizontal_ms * .001 * self.rate
            try:
                y, yq = self._pixels(start + .012*self.rate*scale + phase, .088*self.rate*scale, 320)
                ch, cq = self._pixels(start + .106*self.rate*scale + phase, .044*self.rate*scale, 160,True)
                separator = float(np.median(self.protocol_history.interval(start+.101*self.rate*scale,
                                                                 start+.103*self.rate*scale))) - self.applied_frequency
            except ValueError:
                self._finish("unrecoverable_sync_loss")
                break
            chroma_phase=robot_chroma_phase(self.raw_history,self.rate,start,self.applied_frequency,scale)
            if chroma_phase is None:
                chroma_phase = "Cr" if abs(separator-1500)<90 else "Cb" if abs(separator-2300)<90 else None
            flags = ["timing_recovered"] if inferred else []
            if min(yq,cq) < .8:
                flags.append("low_signal_quality")
            if yq < .2 or (inferred and min(yq,cq) < .5):
                flags.append("missing")
            if chroma_phase is None:
                if self.image.beginning_known:
                    chroma_phase="Cr" if line%2==0 else "Cb"
                    flags.append("chroma_phase_inferred")
                else:
                    flags.append("chroma_phase_unknown")
            comp = dict(y=y, ch=ch, phase=chroma_phase, flags=flags, confidence=min(yq,cq), start=start)
            self.components[line] = comp
            # Protocol pairing comes from separator phase, never local output-row parity.
            previous = self.components.get(line-1)
            pair = previous if previous and previous["phase"] == "Cr" and chroma_phase == "Cb" else None
            if pair:
                self._render(line-1, pair["ch"], ch, reason="paired_chroma_received")
                self._render(line, pair["ch"], ch)
            else:
                other = next((v["ch"] for v in reversed(list(self.components.values())[:-1])
                              if v["phase"] is not None and v["phase"] != chroma_phase), np.full(160,128.0))
                self._render(line, ch if chroma_phase=="Cr" else other,
                             ch if chroma_phase=="Cb" else other, provisional=True)
            self.next_line += 1
            if self.next_line == 240:
                self._finish("normal_end")

    def _pd_rows(self):
        while self.image:
            pair=self.next_line
            start=self.clock.predict(pair)
            layout=pd120.channel_layout(self.rate,start,self.clock.period,self.horizontal_ms)
            if self.pd_channels is None:
                end=sum(layout["cb"])
                if self.history.latest < end+2:
                    return
                self._recover_sync(pair,start,.020,self.clock.period/(pd120.PAIR_SECONDS*self.rate))
                start=self.clock.predict(pair)
                layout=pd120.channel_layout(self.rate,start,self.clock.period,self.horizontal_ms)
                self._pixel_band_reference(start,self.clock.period/(pd120.PAIR_SECONDS*self.rate))
                inferred=pair not in self.observed_lines
                self.sync_gap=self.sync_gap+1 if inferred else 0
                if self.sync_gap>(32 if self.clock.confidence>=.7 else 8):
                    self._finish("unrecoverable_sync_loss")
                    return
                try:
                    y,cr,cb,(yq,cq)=pd120.extract_first(
                        self._pixels,self.rate,start,self.clock.period,self.horizontal_ms,
                        chroma_reader=lambda a,b,c:self._pixels(a,b,c,True), separate_quality=True)
                except ValueError:
                    self._finish("unrecoverable_sync_loss")
                    return
                rendered_cr,rendered_cb=self._chroma(cr,cb,[y])
                self.pd_channels=dict(cr=cr,cb=cb,cq=cq,inferred=inferred,y=y,yq=yq,
                                      start=start,end=end,rendered_cr=rendered_cr,rendered_cb=rendered_cb)
                self._pd_render(pair*2,y,rendered_cr,rendered_cb,min(yq,cq),inferred,start,end)
            end=sum(layout["y_second"])
            requirement=end+2 if not self.draining else end-.00005*self.rate
            if self.history.latest < requirement:
                return
            channels=self.pd_channels
            cr,cb,cq,inferred=(channels[name] for name in ("cr","cb","cq","inferred"))
            try:
                y,_,_,yq=pd120.extract_second(self._pixels,self.rate,start,self.clock.period,cr,cb,self.horizontal_ms)
            except ValueError:
                self._finish("unrecoverable_sync_loss")
                return
            cr,cb=self._chroma(cr,cb,[channels["y"],y])
            if (not np.array_equal(cr,channels["rendered_cr"])
                    or not np.array_equal(cb,channels["rendered_cb"])):
                self._pd_render(pair*2,channels["y"],cr,cb,min(channels["yq"],cq),inferred,
                                channels["start"],channels["end"],reason="shared_chroma_refined")
            self._pd_render(pair*2+1,y,cr,cb,min(cq,yq),inferred,start,end)
            self.pd_channels=None
            self.next_line+=1
            if self.next_line==pd120.PAIRS:
                self._finish("normal_end")

    def _recover_sync(self,line,start,duration,scale):
        if line in self.observed_lines:
            return
        observed=matched_sync(self.raw_history,self.rate,start,duration,self.applied_frequency,scale)
        if observed is not None and self.clock.observe(line,*observed):
            self.observed_lines[line]=observed[1]
            self.last_sync=observed[0]
            self._noise_reference(observed[0])
            self._frequency_reference(observed[0], observed[1])
            if self.diagnostics:
                self.diagnostics(dict(source="matched_sync",line=line,sample=observed[0],confidence=observed[1]))

    def _frequency_reference(self, start, confidence):
        if not self.auto_frequency or confidence < .6:
            return False
        fitted = fit_reference_offset(self.raw_history, self.rate, start+.002*self.rate,
                                      1200, self.measured_frequency)
        if fitted is None:
            return False
        self.reference_offsets.append(fitted)
        if len(self.reference_offsets) >= 3:
            observations = np.asarray(self.reference_offsets)
            self.measured_frequency += .1 * (float(np.median(observations[:,0])) - self.measured_frequency)
            self.frequency_confidence = min(1.,len(observations)/8) * float(np.median(observations[:,1]))
            self.frequency_source = "raw_sync_fit"
            self.detector.offset = self.applied_frequency
        return True

    def _noise_reference(self, start):
        ratio = reference_noise_ratio(self.raw_history, self.rate, start + .002*self.rate,
                                      1200, self.applied_frequency)
        if ratio is not None:
            self.noise_reference_ratio = ratio if self.noise_reference_ratio is None else .9*self.noise_reference_ratio + .1*ratio

    def _chroma(self, cr, cb, guides):
        if (self.auto_noise_reduction and self.noise_reference_ratio is not None
                and self.noise_reference_ratio > .02):
            return guided_chroma_noise_reduction(cr,cb,guides)
        return cr,cb

    def _pd_render(self,row,y,cr,cb,quality,inferred,start,end,reason=None):
        flags=["timing_recovered"] if inferred else []
        if quality<.8:
            flags.append("low_signal_quality")
        if quality<.2 or (inferred and quality<.5):
            flags.append("missing")
        rgb=display_adjust(ycrcb_to_rgb(y,cr,cb),**self.display)
        self.image.row(row,rgb,quality,flags,reason,received_row_sequence=row,
                       physical_scan_line=row//2,
                       protocol_row_index=row if self.image.beginning_known else None,
                       original_position_known=self.image.beginning_known,
                       line_start_sample=start,emitted_at_sample=self.samples,row_audio_end_sample=end)

    def _render(self, line, cr, cb, reason=None, provisional=False):
        comp = self.components[line]
        flags = list(comp["flags"])
        if provisional:
            flags.append("interpolated_chroma")
        guides = [comp["y"]]
        partner = self.components.get(line-1 if comp["phase"]=="Cb" else line+1)
        if not provisional and partner is not None:
            guides.append(partner["y"])
        # Retain native 160-sample chroma until both luminance rows can guide it.
        # Each horizontal Y parity is a guide, preserving even one-pixel text.
        guides = np.asarray(guides).reshape(-1,160,2).transpose(0,2,1).reshape(-1,160)
        cr,cb = self._chroma(cr,cb,guides)
        centers = (np.arange(160)+.5)*2
        cr,cb = (np.interp(np.arange(320)+.5,centers,channel) for channel in (cr,cb))
        rgb = display_adjust(ycrcb_to_rgb(comp["y"], cr, cb), **self.display)
        self.image.row(line, rgb, comp["confidence"] * (.8 if provisional else 1), flags, reason,
                       received_row_sequence=line, physical_scan_line=line,
                       protocol_row_index=line if self.image.beginning_known else None,
                       original_position_known=self.image.beginning_known,
                       chroma_phase=comp["phase"], line_start_sample=comp["start"],
                       emitted_at_sample=self.samples,
                       row_audio_end_sample=comp["start"]+self.clock.period)

    def status(self):
        value = dict(sample_position=self.samples, mode=self.image.mode if self.image else None,
                     frequency_offset_hz=self.measured_frequency, applied_frequency_correction_hz=self.applied_frequency,
                     frequency_confidence=self.frequency_confidence, frequency_locked=self.frequency_confidence>=.7,
                     frequency_reference_source=self.frequency_source, auto_frequency=self.auto_frequency,
                     auto_slant=self.auto_slant, horizontal_offset_ms=self.horizontal_ms,
                     manual_frequency_offset_hz=self.manual_frequency,
                     manual_slant_ppm=self.manual_ppm, impulse_rejection=self.impulse_rejection,
                     noise_reduction_strength=self.noise_reduction,
                     auto_noise_reduction=self.auto_noise_reduction,
                     reference_noise_ratio=self.noise_reference_ratio,
                     automatically_noise_reduced_channels=self.noise_reduced_channels,
                     rows_decoded=len(self.image.rows) if self.image else 0,
                     sinefit_channels_used=self.fit_channels,
                     pixel_band=self.active_pixel_band,
                     buffered_audio_samples=len(self.pending)//2,
                     frequency_history_capacity_samples=self.history.capacity)
        if self.clock:
            value.update(self.clock.status(self.next_line))
        return value

    def _finish(self, reason):
        if self.image:
            self.image.finish(reason, self.status())
        self.image = None
        self.clock = None
        self.components = {}
        self.observed_lines = {}
        self.candidates.clear()
        self.next_line = 0
        self.pd_channels = None
        self.detector.search_offset = True

    def control(self, command):
        if not isinstance(command, dict):
            raise ValueError("command must be a JSON object")
        name = command.get("command")
        if name == "status":
            pass
        elif name == "reset":
            self._finish("manual_reset")
            self.pending.clear()
            self.measured_frequency = 0
            self.frequency_confidence = 0
            self.frequency_source = None
            self._pipeline()
        elif name == "mode":
            mode = command.get("mode")
            if mode not in ("auto", "Robot36", "PD120"):
                raise ValueError("mode must be auto, Robot36 or PD120")
            self._finish("manual_reset")
            self.forced = None if mode == "auto" else mode
        elif name in ("frequency", "slant", "horizontal", "noise_reduction", "display"):
            self._adjust(name, command)
        elif name == "impulse_rejection":
            self.impulse_rejection = self._boolean(command, "enabled")
        elif name == "discontinuity":
            lost = command.get("lost_samples")
            if lost is not None and (isinstance(lost,bool) or not isinstance(lost,int) or lost < 0):
                raise ValueError("lost_samples must be a nonnegative integer or null")
            usable=len(self.pending)-len(self.pending)%2
            if usable:
                self._process(np.frombuffer(bytes(self.pending[:usable]),dtype="<i2").astype(float)/32768)
            if len(self.pending)%2:
                self.emit(dict(type="warning",code="unmatched_pcm_byte",message="discontinuity discarded one unmatched PCM byte"))
            self.pending.clear()
            # Close this recoverable segment, preserving authoritative rows; the next
            # segment has unknown transmitter position, so never invent row numbering.
            self._finish("audio_discontinuity")
            self.samples += lost or 0
            self._pipeline()
            self.emit(dict(type="warning", code="audio_discontinuity", lost_samples=lost,
                           timeline_continuity_known=lost is not None))
        else:
            raise ValueError("unknown control command")
        self.emit(dict(type="status", command=name, **self.status()))

    @staticmethod
    def _boolean(command, key):
        if not isinstance(command.get(key), bool):
            raise ValueError(f"{key} must be a boolean")
        return command[key]

    @staticmethod
    def _number(command, key, low, high):
        x = command.get(key)
        if isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) or not low<=x<=high:
            raise ValueError(f"{key} must be a finite number in [{low}, {high}]")
        return float(x)

    def _adjust(self, name, command):
        if name == "frequency":
            auto = self._boolean(command,"auto")
            manual = self._number(command,"offset_hz",-300,300) if "offset_hz" in command else self.manual_frequency
            self.auto_frequency, self.manual_frequency = auto, manual
            self.detector.offset = self.applied_frequency
        elif name == "slant":
            auto = self._boolean(command,"auto")
            ppm = self._number(command,"ppm",-20000,20000) if "ppm" in command else self.manual_ppm
            self.auto_slant, self.manual_ppm = auto, ppm
            if self.clock:
                old_position = self.clock.predict(self.next_line)
                self.clock.auto, self.clock.manual_ppm = auto, ppm
                if not auto:
                    self.clock.period = self.clock.nominal * (1+ppm/1e6)
                    self.clock.origin = old_position-self.next_line*self.clock.period
        elif name == "horizontal":
            self.horizontal_ms = self._number(command,"offset_ms",-5,5)
        elif name == "noise_reduction":
            if "auto" in command:
                automatic = self._boolean(command,"auto")
                if automatic and "strength" in command:
                    raise ValueError("automatic noise reduction does not accept a manual strength")
                strength = self._number(command,"strength",0,1) if "strength" in command else 0.0
            else:
                automatic = False
                strength = self._number(command,"strength",0,1)
            self.auto_noise_reduction, self.noise_reduction = automatic, strength
        elif name == "display":
            limits = dict(brightness=(-1,1),contrast=(0,4),gamma=(.1,5),saturation=(0,4))
            adjusted = {k:self._number(command,k,*v) for k,v in limits.items() if k in command}
            self.display.update(adjusted)

    def eof(self):
        if self.closed:
            return
        usable = len(self.pending) - len(self.pending)%2
        if usable:
            self._process(np.frombuffer(bytes(self.pending[:usable]),dtype="<i2").astype(float)/32768)
        if len(self.pending)%2:
            self.emit(dict(type="warning",code="unmatched_pcm_byte",message="EOF discarded one unmatched PCM byte"))
        self.pending.clear()
        # Drain only filter tail; appended zeros do not count as received image audio.
        timeline = self.samples
        self.draining = True
        self._process(np.zeros(self.dsp.delay+3))
        self.samples = timeline
        self._finish("eof")
        self.closed = True
