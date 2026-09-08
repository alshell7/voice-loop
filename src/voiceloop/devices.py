"""Native device discovery; import the audio backend only when needed."""

import sys
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Device:
    id: str
    name: str
    channels: int
    loopback: bool = False

    @property
    def label(self) -> str:
        return self.name + (" · system audio" if self.loopback else "")


@dataclass
class Devices:
    inputs: list[Device]
    outputs: list[Device]
    default_input: str = ""
    default_output: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def discover() -> Devices:
    import soundcard as sc

    inputs = [
        Device(str(d.id), d.name, d.channels, d.isloopback)
        for d in sc.all_microphones(include_loopback=True)
    ]
    outputs = [Device(str(d.id), d.name, d.channels) for d in sc.all_speakers()]
    default_input = sc.default_microphone()
    default_output = sc.default_speaker()
    return Devices(
        inputs,
        outputs,
        str(default_input.id) if default_input else "",
        str(default_output.id) if default_output else "",
    )


def loopback_for(speaker: Device, devices: Devices) -> Device | None:
    # WASAPI loopback has the render endpoint ID; PulseAudio uses sink-name.monitor.
    for device in devices.inputs:
        if device.loopback and device.id in (speaker.id, speaker.id + ".monitor"):
            return device
    # PulseAudio speaker IDs can be indices while monitor IDs are names.
    if sys.platform.startswith("linux"):
        return next(
            (
                d
                for d in devices.inputs
                if d.loopback and d.name in (speaker.name, "Monitor of " + speaker.name)
            ),
            None,
        )
    return None


@dataclass(frozen=True)
class SessionConfig:
    microphone: Device
    meeting: Device
    speaker: Device
    virtual_mic: Device | None = None
    mode: str = "direct"
    left_channel: str = "microphone"
    right_channel: str = "meeting"

    def validate(self) -> None:
        if {self.left_channel, self.right_channel} != {"microphone", "meeting"}:
            raise ValueError("Assign microphone and meeting audio to different recording channels.")
        if self.mode not in ("direct", "bridge"):
            raise ValueError("Choose direct capture or virtual bridge.")
        if self.microphone.loopback:
            raise ValueError("Choose a physical microphone for your voice.")
        if self.microphone.id == self.meeting.id:
            raise ValueError("Your microphone and meeting audio must be different inputs.")
        if self.mode == "bridge":
            if self.virtual_mic is None:
                raise ValueError("Select the playback side of your virtual microphone cable.")
            if self.virtual_mic.id == self.speaker.id:
                raise ValueError("Your physical speaker cannot also be the virtual microphone.")
            # Windows loopback shares the output ID. Pulse monitors append .monitor.
            meeting_output = self.meeting.id.removesuffix(".monitor")
            if meeting_output in (self.speaker.id, self.virtual_mic.id):
                raise ValueError(
                    "Feedback loop: use separate cables for microphone and meeting audio."
                )
            if self.microphone.id.removesuffix(".monitor") == self.virtual_mic.id:
                raise ValueError("Feedback loop: choose your physical microphone.")
        if min(self.microphone.channels, self.meeting.channels, self.speaker.channels) < 1:
            raise ValueError("A selected device has no audio channels. Refresh devices.")


VIRTUAL_NAMES = ("voiceloop", "vb-audio", "blackhole", "cable input", "cable output", "hi-fi cable")


def is_virtual(device: Device) -> bool:
    return any(name in device.name.casefold() for name in VIRTUAL_NAMES)


@dataclass(frozen=True)
class BridgeEndpoints:
    microphone_feed: Device
    meeting_source: Device
    microphone: Device
    speaker: Device


def bridge_endpoints(devices: Devices) -> BridgeEndpoints | None:
    """Resolve complete named paths; never claim that one cable is a duplex bridge."""

    def named(items, name):
        # WASAPI adds the driver manufacturer to the user-editable endpoint name.
        return next(
            (d for d in items if d.name == name or d.name.startswith(name + " (VB-Audio")),
            None,
        )

    mic = named([d for d in devices.inputs if not d.loopback], "VoiceLoop Mic")
    speaker = named(devices.outputs, "VoiceLoop Speaker")
    feed = named(devices.outputs, "VoiceLoop Mic Feed")
    # macOS aliases wrap a duplex BlackHole device; the same ID has both directions.
    if feed is None and mic:
        feed = next((d for d in devices.outputs if d.id == mic.id), None)
    source = loopback_for(speaker, devices) if speaker else None
    if source is None and speaker:
        source = next((d for d in devices.inputs if d.id == speaker.id), None)
    if all((mic, speaker, feed, source)) and feed.id != speaker.id:
        return BridgeEndpoints(feed, source, mic, speaker)
    return None


def simple_config(microphone: Device, speaker: Device, devices: Devices) -> SessionConfig:
    if is_virtual(microphone) or is_virtual(speaker):
        raise ValueError("Simple setup uses your physical microphone and speaker.")
    endpoints = bridge_endpoints(devices)
    if endpoints:
        result = SessionConfig(
            microphone, endpoints.meeting_source, speaker, endpoints.microphone_feed, "bridge"
        )
    else:
        source = loopback_for(speaker, devices)
        if source is None:
            raise ValueError("Finish virtual device setup first, or choose sources in Advanced.")
        result = SessionConfig(microphone, source, speaker)
    result.validate()
    return result
