"""Safe standalone HTML export and native dialog rendering from transcript JSON."""

import html
import json
import math
from pathlib import Path

from voiceloop.library import audio_parts


def timecode(value) -> str:
    seconds = max(0, int(float(value)))
    return f"{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"


def render_transcript(data: dict, *, native=False) -> str:
    def escape(value):
        return html.escape(str(value), quote=True)

    meta = data.get("metadata", {})
    title = meta.get("contact") or "Session transcript"
    subtitle = " · ".join(
        str(v) for v in (meta.get("tool"), data.get("started_at", "")[:19].replace("T", " ")) if v
    )
    rows = []
    for index, segment in enumerate(data.get("segments", [])):
        start = float(segment.get("start", 0))
        if not math.isfinite(start) or start < 0:
            continue
        link = f"seek:{start:.3f}" if native else f"#segment-{index}"
        speaker = escape(segment.get("speaker") or "Speaker")
        text = escape(segment.get("text", "")).replace("\n", "<br>")
        rows.append(
            f'<section class="segment" id="segment-{index}" data-time="{start:.3f}">'
            f'<p class="byline"><a href="{link}">{timecode(start)}</a>'
            f' &nbsp; <b>{speaker}</b></p><p class="words">{text}</p></section>'
        )
    return (
        f'<h1>{escape(title)}</h1><p class="subtitle">{escape(subtitle)}</p>'
        f'<p class="note">{escape(data.get("speaker_labels", ""))}</p>'
        + ("".join(rows) or '<p class="note">No speech was detected in this recording.</p>')
    )


STYLE = """
:root{color-scheme:light}*{box-sizing:border-box}body{margin:0;background:#f6f7f9;
color:#20242d;font:16px/1.65 'Segoe UI',system-ui,sans-serif}main{max-width:850px;
margin:40px auto;padding:32px 40px;background:white;border-radius:20px}
h1{font-size:30px;line-height:1.25;margin:0 0 10px}p{margin:0 0 12px}
.subtitle,.note{color:#626977}.note{font-size:13px;margin:20px 0 30px}
.segment{padding:18px 0;border-bottom:1px solid #e9ebf0}.byline{font-size:13px;
margin-bottom:8px}.words{max-width:70ch}a{color:#005bc4;text-underline-offset:3px}
a:focus-visible,select:focus-visible,audio:focus-visible{outline:2px solid #338ef7;
outline-offset:4px}::selection{background:#c8e0ff}audio{width:100%;margin-top:12px}
.player{position:sticky;top:0;background:white;padding:12px 0}.player label{font-size:13px}
select{padding:8px;border:1px solid #dce2ea;border-radius:8px;background:#f4f5f7}
@media(max-width:600px){main{margin:0;padding:24px 20px;border-radius:0}h1{font-size:25px}}
"""


def save_html(directory: Path) -> Path:
    data = json.loads((directory / "transcript.json").read_text(encoding="utf-8"))
    manifest = json.loads((directory / "session.json").read_text(encoding="utf-8"))
    data["metadata"] = manifest.get("metadata", {})
    files = audio_parts(directory, manifest)
    options = "".join(f'<option value="{i}">Audio part {i + 1}</option>' for i in range(len(files)))
    parts = [
        {"file": p.name, "start": float(info["start_frame"]) / 48000}
        for p, info in zip(files, manifest["parts"], strict=True)
    ]
    payload = json.dumps(parts).replace("<", "\\u003c")
    document = (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        "style-src 'unsafe-inline'; script-src 'unsafe-inline'; media-src 'self' file:;\">"
        f"<title>Voice Loop transcript</title><style>{STYLE}</style><main>"
        f'<div class="player"><label for="part">Playback &nbsp;</label><select id="part">{options}</select>'
        '<audio id="audio" controls preload="metadata"></audio></div>'
        + render_transcript(data)
        + "</main><script>const parts="
        + payload
        + ";"
        'const player=document.getElementById("audio"),select=document.getElementById("part");'
        "if(parts.length)player.src=parts[0].file;"
        "select.onchange=()=>{player.src=parts[Number(select.value)].file;};"
        'document.querySelectorAll(".segment a").forEach(a=>a.onclick=e=>{e.preventDefault();'
        'const t=Number(a.closest("section").dataset.time);let i=0;'
        "parts.forEach((p,n)=>{if(p.start<=t)i=n;});if(!parts.length)return;"
        "const seek=()=>{player.currentTime=Math.max(0,t-parts[i].start);player.play().catch(()=>{});};"
        "if(Number(select.value)!==i){select.value=String(i);player.src=parts[i].file;"
        'player.addEventListener("loadedmetadata",seek,{once:true});}else seek();});'
        "</script></html>"
    )
    output = directory / "transcript.html"
    temporary = output.with_suffix(".html.tmp")
    temporary.write_text(document, encoding="utf-8")
    temporary.replace(output)
    return output
