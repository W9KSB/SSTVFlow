"""Supported analog mode layouts, in protocol seconds.

Robot72, Martin, Scottie and PD timings: JL Barber, Dayton 2000 mode
specifications, https://www.classicsstv.com/downloads/daytonpaper.pdf
(Robot firmware and PD author). Robot24 is the 160x120, VIS4 full-chroma mode.
Its video allocation uses two units for luminance and one unit for each chroma
channel.

Scottie places its regular sync between the Blue and Red scans, not at the line
break. Rows are therefore anchored on that sync: Green and Blue precede it and
Red follows it, so those channel offsets are negative. Scottie's first line
also opens with an out-of-sequence 9 ms start sync; ``header_offset`` advances
a VIS-established start past it to the row anchor.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Mode:
    vis: int
    width: int
    height: int
    period: float
    sync: float
    family: str
    channels: tuple = ()
    markers: tuple = ()
    header_offset: float = 0.0


MODES = {
    "Robot36": Mode(8, 320, 240, .150, .009, "robot36"),
    "PD120": Mode(95, 640, 496, .508480, .020, "pd"),
    "Robot72": Mode(12, 320, 240, .300, .009, "robot",
                    (("y", .012, .138), ("cr", .156, .069), ("cb", .231, .069)),
                    ((.1505, .154, 1500), (.2255, .229, 2300))),
    "Robot24": Mode(4, 160, 120, .2000125, .006, "robot",
                    (("y", .0072, .09260625), ("cr", .10360625, .046303125),
                     ("cb", .153709375, .046303125)),
                    ((.1001, .1019, 1500), (.1502, .1520, 2300))),
    "MartinM1": Mode(44, 320, 256, .446446, .004862, "rgb",
                     (("g", .005434, .146432), ("b", .152438, .146432), ("r", .299442, .146432))),
    "MartinM2": Mode(40, 320, 256, .226798, .004862, "rgb",
                     (("g", .005434, .073216), ("b", .079222, .073216), ("r", .153010, .073216))),
    "PD180": Mode(96, 640, 496, .754240, .020, "pd"),
    "Scottie1": Mode(60, 320, 256, .428220, .009, "rgb",
                     (("g", -.277980, .138240), ("b", -.138240, .138240),
                      ("r", .010500, .138240)),
                     ((.009, .0105, 1500), (.148740, .150240, 1500)),
                     header_offset=.288480),
    "Scottie2": Mode(56, 320, 256, .277692, .009, "rgb",
                     (("g", -.177628, .088064), ("b", -.088064, .088064),
                      ("r", .010500, .088064)),
                     ((.009, .0105, 1500), (.098564, .100064, 1500)),
                     header_offset=.188128),
    "ScottieDX": Mode(76, 320, 256, 1.050300, .009, "rgb",
                      (("g", -.692700, .345600), ("b", -.345600, .345600),
                       ("r", .010500, .345600)),
                      ((.009, .0105, 1500), (.356100, .357600, 1500)),
                      header_offset=.703200),
    "PD50": Mode(93, 320, 256, .388160, .020, "pd"),
    "PD90": Mode(99, 320, 256, .703040, .020, "pd"),
    "PD160": Mode(98, 512, 400, .804416, .020, "pd"),
    "PD240": Mode(97, 640, 496, 1.0, .020, "pd"),
    "PD290": Mode(94, 800, 616, .937280, .020, "pd"),
}
SUPPORTED_MODES = tuple(MODES)
VIS_MODES = {profile.vis: name for name, profile in MODES.items()}


def sync_matches(profile, duration):
    """Duration gate for a candidate pulse, in seconds."""
    if profile.sync == .004862:
        return .002 <= duration <= .007
    if profile.sync == .006:
        return .004 <= duration <= .009
    if profile.sync == .009:
        return .006 <= duration <= .013
    return .016 <= duration <= .023


def row_span(profile):
    """Seconds from a row anchor to the end of its last picture channel.

    Robot and Martin rows finish with their final channel. A Scottie Red scan
    ends well before its period does, because the next line's separator, Green
    and Blue scans follow it. PD's four scans are derived from the mode period
    rather than listed as channels.
    """
    if not profile.channels:
        return profile.period
    return max(begin + duration for _, begin, duration in profile.channels)
