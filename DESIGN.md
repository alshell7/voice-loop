---
name: Voice Loop
description: A clean, modern native desktop audio utility with white surfaces and blue actions.
colors:
  primary: "#006FEE"
  primary-deep: "#005BC4"
  primary-tint: "#EAF2FF"
  focus: "#338EF7"
  workspace: "#F6F7F9"
  surface: "#FFFFFF"
  text: "#20242D"
  muted: "#626977"
  border: "#E9EBF0"
  control: "#F0F2F5"
  control-text: "#333B49"
  control-hover: "#E5E9EF"
  control-pressed: "#D9E0EA"
  field: "#F4F5F7"
  field-border: "#E5E8ED"
  track: "#EDEFF3"
  badge: "#ECEEF2"
  badge-text: "#596170"
  icon: "#697386"
  level: "#17A673"
  tray-muted: "#E5484D"
  tray-off: "#8F99A8"
typography:
  headline:
    fontFamily: "Segoe UI, Helvetica Neue, sans-serif"
    fontSize: "28px"
    fontWeight: 700
  title:
    fontFamily: "Segoe UI, Helvetica Neue, sans-serif"
    fontSize: "18px"
    fontWeight: 600
  body:
    fontFamily: "Segoe UI, Helvetica Neue, sans-serif"
    fontSize: "14px"
  label:
    fontFamily: "Segoe UI, Helvetica Neue, sans-serif"
    fontSize: "13px"
    fontWeight: 600
  small:
    fontFamily: "Segoe UI, Helvetica Neue, sans-serif"
    fontSize: "12px"
  timer:
    fontFamily: "Consolas, Menlo, monospace"
    fontSize: "26px"
rounded:
  meter: "3px"
  compact: "8px"
  text-field: "10px"
  control: "11px"
  badge: "12px"
  card: "20px"
spacing:
  tight: "5px"
  small: "8px"
  content: "14px"
  section: "18px"
  transport: "20px"
  inset: "22px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.surface}"
    rounded: "{rounded.control}"
    padding: "11px 17px"
  button-primary-hover:
    backgroundColor: "{colors.primary-deep}"
  button-secondary:
    backgroundColor: "{colors.control}"
    textColor: "{colors.control-text}"
    rounded: "{rounded.control}"
    padding: "11px 17px"
  button-secondary-hover:
    backgroundColor: "{colors.control-hover}"
  button-secondary-pressed:
    backgroundColor: "{colors.control-pressed}"
  navigation-selected:
    backgroundColor: "{colors.primary-tint}"
    textColor: "{colors.primary-deep}"
    rounded: "{rounded.control}"
    padding: "12px 16px"
  segment-selected:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.compact}"
    padding: "7px 16px"
  field:
    backgroundColor: "{colors.field}"
    textColor: "{colors.text}"
    rounded: "{rounded.control}"
    padding: "10px 16px"
  text-field:
    backgroundColor: "{colors.field}"
    textColor: "{colors.text}"
    rounded: "{rounded.text-field}"
    padding: "11px 13px"
  card:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.card}"
    padding: "18px 22px"
  badge:
    backgroundColor: "{colors.badge}"
    textColor: "{colors.badge-text}"
    typography: "{typography.small}"
    rounded: "{rounded.badge}"
    padding: "7px 12px"
---

# Design System: Voice Loop

## Overview

**Creative North Star: "Clean, modern native desktop"**

Voice Loop v0.3 extends the user's confirmed clean, modern, HeroUI-inspired
direction to native PySide6 widgets. A pale gray workspace, white surfaces, and
blue actions make routing choices easy to scan. The system feels calm and
practical, with generous space around controls and brief explanations beside
unfamiliar audio concepts. HeroUI supplies the visual reference; Qt Fusion and
the stylesheet implement the interface.

The shipped source is `src/voiceloop/ui.py`, `src/voiceloop/ui_extras.py`,
`src/voiceloop/desktop.py`, and `src/voiceloop/transcript_html.py`, with authored SVG
paths and resources. This refresh preserves the incumbent Qt system and records
its floating controls, preferences, library, and transcript viewer. Seven native
Windows screenshots in `.impeccable/review/v03/` show expanded and compact
controls, off and muted recording states, two library sizes, preferences, and a
transcript with synthetic content. They establish visual evidence, not hardware
or cloud-service validation. macOS and Linux rendering remains unverified.

The extension sidecar `.impeccable/design.json` contains panel previews translated
from native controls. Its HTML/CSS snippets are documentation, not application
markup; generated tonal ramps are display aids rather than shipped color scales.

**Key Characteristics:**

- White, gently rounded panels on a quiet gray workspace.
- Blue actions and selection states; green reserved for audio level meters.
- Native keyboard controls with visible focus and contextual help.
- Explicit recording state, with compact floating and tray access to sessions.

## Colors

Blue carries interaction; cool neutrals carry layout and reading. The frontmatter
records the source values and is the normative token layer.

### Primary

- **Action blue** (`primary`) identifies primary buttons, the product mark, and
  device icons in Audio setup.
- **Deep blue** (`primary-deep`) identifies primary-button hover, selected
  navigation text, list selections, and external attribution links.
- **Pale blue** (`primary-tint`) supports selected navigation, list selections,
  and help-button hover. **Focus blue** (`focus`) identifies keyboard focus.

### Secondary

- **Live green** (`level`) fills the two audio meters. It indicates input level,
  not recording consent or saved-file state.

### Neutral

- **Workspace gray** and **surface white** separate the application background
  from the sidebar, content panels, transport, and dialog.
- **Ink** (`text`) and **muted gray** (`muted`) distinguish primary content from
  explanatory text. Muted text is still used for information the user must read.
- **Soft borders**, **control gray**, and **field gray** define groups and
  editable choices without heavy outlines. Badges retain their neutral treatment
  when their status text changes.

**The Written State Rule.** Recording, no-save activity, setup readiness, and
errors must be named in text; neither blue nor green establishes those states.
Mute has both a checked treatment and an explicit Unmute action label.

## Typography

The UI stylesheet uses Segoe UI, Helvetica Neue, and a sans-serif fallback. The
application requests Segoe UI on Windows and Helvetica Neue on other platforms;
Qt resolves availability. This is a native utility type system, not a webfont or
promotional display system. The timer uses Consolas, Menlo, and a monospace
fallback for steady numeric measurement.

The hierarchy runs from a bold page headline to a semibold panel title, regular
body text, semibold field labels, and smaller metadata. The product label is a
compact bold identifier (19px), while the timer is a separate measurement role.
The floating timer reduces to 23px. Transcript reading has its own document
scale: the native text browser uses 15px body copy and a 25px heading; the
standalone HTML uses 16px body copy with 1.65 line height and a 30px heading.
These reading-surface adjustments do not replace the application control scale.
Sizes in the frontmatter are Qt stylesheet pixels, expressed in logical UI
coordinates; line height and letter spacing are left to Qt and the selected font.
Do not inherit the previous Tk point sizes or manual DPI multiplier.

## Layout

A fixed sidebar (190 logical pixels) contains the brand, Session, Audio setup,
Recordings, and Preferences navigation, followed by Floating controls, a quiet
local-privacy statement, and version. The flexible workspace uses a page header,
a vertically scrollable content area, then transport and status. The header's
status badge stays visible outside the scrolling pages. Recordings hides the
main transport to give its table more height; floating/tray controls remain the
route to stopping a session there. Changing pages does not interrupt audio.

The initial window is 1060 by 820, with a minimum of 820 by 640 logical pixels.
Main content margins are 26 left/right, 22 top, and 18 bottom. Cards use 22
horizontal and 18 vertical inset, with a 14-pixel internal gap; page cards are
18 pixels apart. Qt handles high-DPI scaling. The layout compresses to its minimum
width and permits vertical scrolling, with no separate mobile breakpoint or
horizontal page scrolling.

Simple stacks two full-width physical-device fields. Advanced expands the same
card with routing and virtual-path fields, then places Left channel and Right
channel side by side. The transport pairs equal-width input meters above the
action row, with elapsed time aligned to the right. Long explanatory text and
paths wrap; device dropdowns can shrink and preserve full names in item tooltips.

The floating window is 420 logical pixels wide and fits its height to visible
content. Its header, status/timer row, mode/on-off/mute row, and bottom actions
remain when meeting details and storage are collapsed. The expanded state stacks
the two tag fields. The Recordings card places search above three equal-width
filters, with a scrollable table above its fixed action/pagination row. Its
denser inset is 18 horizontal and 14 vertical pixels, with 10-pixel gaps.

The session viewer starts at 850 by 760 with a 650 by 540 minimum. Tags sit above
the flexible transcript area; playback and file actions stay below it. The
standalone HTML is an export-specific reading layout: an 850-pixel maximum white
sheet, 70ch text measure, and sticky audio controls. At 600px and below it uses
20px horizontal inset and drops the outer card corners. This breakpoint belongs
to exported HTML, not the native app.

## Elevation & Depth

Depth comes from white surfaces on the gray workspace, pale selected states, and
fine borders. Panels and transport have a one-pixel soft border and no decorative
shadow. Native popup and dialog rendering belongs to Qt and the operating system;
the app does not add shadow or blur effects. The frameless floating panel adds a
subtly blue-white surface and cool border, with whole-window opacity adjustable
from 65–100% (95% by default). It does not use backdrop blur. There are no animated
page or hover transitions. Motion is limited to functional meter, clock, playback,
and progress updates.

## Shapes

Large rounded cards enclose related decisions. Controls share a smaller rounded
shape; selected segments sit inside a rounded gray tray. Badges are compact
rounded rectangles, while meters are thin rounded bars. These radii are recorded
in the frontmatter rather than inferred from a web framework.

Icons are consistent authored SVG paths with rounded caps and joins; recording
and stop symbols use solid geometric forms. The chevron resource is a small
stroked downward arrow. These are programmatic vector assets, with no raster
illustration, glyph substitutes, or external icon-font dependency.

## Components

### Buttons and navigation

Primary actions use blue with white text and deepen on hover. Secondary buttons
use neutral fill, with darker hover and pressed states. Disabled states use pale
fill and muted text. The left-aligned sidebar uses blue text on pale blue for the
selected page. Simple/Advanced is an exclusive segmented selection: the active
segment is white on a neutral tray. Checked buttons, including mute, use the pale
blue selection treatment with a fine blue border. Icon-only controls use SVGs,
accessible action names, and matching tooltips; names change when an action
reverses, as with Collapse/Expand meeting details.

Push buttons, device fields, and help buttons receive a two-pixel blue border on
focus. Help buttons have accessible names, show explanations on hover, click, or
keyboard focus, and hide keyboard-opened help on focus loss. The driver attribution
link supports keyboard interaction and uses deep blue for legibility.

### Device fields and channel roles

Read-only dropdowns sit beneath explicit labels and adjacent help icons. Field
labels are keyboard buddies; controls have accessible names. Hover changes the
field fill and border, focus supplies the blue border, and disabled choices are
muted. Lists use a white background and pale-blue selection. Missing saved devices
produce a clear unavailable placeholder rather than silently choosing another.

Search and API-key fields use the same gray fill with gently rounded corners.
Editable tag dropdowns reuse the dropdown shell without nesting a second visible
input border. Contact suggestions match typed substrings without case sensitivity;
the field permits new names. A saved contact is metadata, not a speaker-identity
claim. The key field masks its contents and is cleared after saving or removal.

Simple shows only physical Microphone and Speaker. Advanced reveals Audio
routing, Meeting audio source, a conditional Virtual microphone feed, and paired
Left/Right channel selectors. Channel roles remain complementary. These recording
roles do not rename the two live meters, which always identify their audio source.

### Panels and session transport

Cards group audio choices, meeting-app guidance, setup, and recordings. Titles
lead, optional secondary explanations follow, and actions sit with their context.
The transport remains below Session, Audio setup, and Preferences, with Microphone
and Meeting audio meters, numeric dB readings, Start session, Stop, Mute mic, and
elapsed time. Recordings omits this panel. The meters are
six pixels tall and show input level only after a session starts. Configuration,
audio-device refresh, setup, and recording-folder changes are unavailable during active audio
or setup work; Stop reflects whether the audio engine can stop.

### Consent and status

The main Start session consent dialog opens before audio devices do. It states the local save path
and offers Record session, Route audio only or Monitor only, and Cancel. Cancel
has initial focus and is the default; Escape cancels. The dialog uses the same
white surface, typography, and button system, with a 520-pixel minimum width.

The neutral header badge and persistent status copy distinguish Recording,
Audio active · not recording, Starting, Finishing, idle, errors, and saved paths.
Setup has visible progress and reports success or a concrete failure. Stopping or
quitting a running session preserves the visible finishing state while audio ends.

Floating controls instead make the recording choice directly: Route only / Record
too stays visible and locks while audio is active. Turn on becomes Turn off, and
Mute becomes Unmute when checked. State copy distinguishes Off, Opening audio,
Finishing session, routing, local recording, and muted activity. Collapse hides
only the meeting details and storage. Minimize hides the panel to the tray; the
separate Open Voice Loop action brings up the full app. Preserve the difference
between changing window visibility and ending audio.

### Preferences and tray

Preferences uses two familiar cards for startup/opacity and OpenAI transcription.
Checkboxes have an authored white check on blue when selected. Opacity and
playback sliders share a thin neutral track, blue filled range, and blue circular
handle with a white border; both receive visible keyboard focus. The opacity
label includes its numeric percentage.

Upload and billing copy precedes the model/key controls. The automatic-upload
checkbox states the consequence in its label and is off by default. Key status,
transcription progress, cancellation, and errors use written feedback. The tray
uses white native menus with pale-blue selection, checkable device choices,
grouping separators, and separate Quit Voice Loop and Force quit entries.
The tray waveform carries a small white-bordered dot: level green while active,
tray-muted red while active and muted, and tray-off grey while idle. The tooltip
provides the written state. Icons include native sizes from 16 to 64 pixels.
Searchable tool/contact completion lists have their own explicit white popup
palette with dark text and pale-blue selection, including inactive palette groups;
they are top-level windows and cannot rely on combobox descendant styling.

### Recordings

The local library uses a plain table inside a white card, with contact and session
time stacked in the first column, then tool, length, and written status. Rows are
62 pixels tall; the contact/session column stretches while the others fit their
content. Header and selection colors reuse the field and selection palette.
Search covers contact, tool, or date; tool, recording/transcription state, and
date-range selectors refine the result. Eight sessions form a page; previous/next
SVG buttons have accessible names and disable at the boundaries. The page fraction
has a tooltip with total count. Play is primary, followed by View transcript and
Transcribe. Playback is unavailable during live audio. Folder actions and the
current path sit outside the library card. Distinct empty states explain an empty
library and unmatched filters without fabricated example sessions.

### Transcript reader

The native session dialog keeps tags, reading, playback, and file actions in
separate rows. The bordered text area leads with the contact or Session transcript,
then tool/date metadata and any speaker-label limitation. Each segment pairs an
underlined blue timestamp and bold speaker label with regular text below. The
content comes from escaped transcript JSON. Timestamp links seek playback; the
slider supports arrow-key steps of one second and Page Up/Down steps of ten
seconds. Playback uses the chosen physical speaker and requires live audio off.
Open HTML, Open JSON, and Open session folder expose the local artifacts. The HTML
export retains the palette and segment hierarchy, with browser audio controls and
local part selection. Export-specific typography and layout remain scoped to that
reading surface.

## Do's and Don'ts

### Do:

- **Do** preserve the white/gray hierarchy and blue interaction palette.
- **Do** keep recording status visible and provide session access through floating/tray controls when the library hides the main transport.
- **Do** expose audio terminology through clear labels and keyboard-accessible help.
- **Do** retain full device names in tooltips when a selector cannot display them.
- **Do** preserve the visible no-save mode and the main Start session dialog's Cancel-first behavior.
- **Do** use the short meeting-facing names VoiceLoop Mic and VoiceLoop Speaker.
- **Do** pair checked controls and audio activity with explicit action and status text.
- **Do** keep tag metadata distinct from diarization labels and upload choices explicit.

### Don't:

- **Don't** use meter color as evidence that recording is enabled or saved.
- **Don't** expand Simple into a list of virtual devices or channel assignments.
- **Don't** apply a manual DPI multiplier on top of Qt's logical-coordinate layout.
- **Don't** add decorative animation or raster artwork to this utility hierarchy.
- **Don't** claim macOS/Linux visual parity from Windows screenshots alone.
