"""
Max for Live Filter Device Example
===================================
A stereo lowpass filter audio effect with two automatable Live parameters.

Signal chain:
    plugin~ (stereo from track) → lores~ (left/right) → plugout~ (stereo)

Controls (live.dial, shown in the device view via presentation mode):
    Cutoff     20 Hz - 20 kHz, exponential, default 1 kHz  → lores~ cutoff
    Resonance  0 - 95 %, default 30 %  → * 0.01 → lores~ resonance

Usage:
    python main.py
    → Generates m4l_filter_device.amxd
    → Drag onto an audio track in Ableton Live
"""

import maxpylang as mp

patch = mp.MaxPatch()

# === CONTROLS ===
patch.set_position(30, 30)
patch.place("live.comment === CONTROLS ===")[0]

patch.set_position(30, 60)
cutoff = patch.place(mp.MaxObject(
    "live.dial",
    parameter_longname="Cutoff",
    parameter_mmin=20.,
    parameter_mmax=20000.,
    parameter_initial=1000.,
    parameter_unitstyle="hertz",
    parameter_exponent=3.,
))[0]
cutoff.present(8, 8)

patch.set_position(200, 60)
resonance = patch.place(mp.MaxObject(
    "live.dial",
    parameter_longname="Resonance",
    parameter_mmin=0.,
    parameter_mmax=95.,
    parameter_initial=30.,
    parameter_unitstyle="percent",
))[0]
resonance.present(64, 8)

patch.set_position(200, 120)
res_scale = patch.place("* 0.01")[0]

# === AUDIO ===
patch.set_position(30, 160)
patch.place("live.comment === AUDIO ===")[0]

patch.set_position(30, 190)
plugin = patch.place("plugin~")[0]

patch.set_position(30, 240)
filt_l = patch.place("lores~ 1000 0.3")[0]

patch.set_position(200, 240)
filt_r = patch.place("lores~ 1000 0.3")[0]

patch.set_position(30, 300)
plugout = patch.place("plugout~")[0]

# === CONNECTIONS ===
patch.connect(
    # cutoff dial → both filters' cutoff inlets
    [cutoff.outs[0], filt_l.ins[1]],
    [cutoff.outs[0], filt_r.ins[1]],
    # resonance dial (percent) → 0-0.95 → both filters' resonance inlets
    [resonance.outs[0], res_scale.ins[0]],
    [res_scale.outs[0], filt_l.ins[2]],
    [res_scale.outs[0], filt_r.ins[2]],
    # stereo audio path
    [plugin.outs[0], filt_l.ins[0]],
    [plugin.outs[1], filt_r.ins[0]],
    [filt_l.outs[0], plugout.ins[0]],
    [filt_r.outs[0], plugout.ins[1]],
)

# === DEVICE ===
# open in presentation mode so Live shows the two dials as the device UI
patch.set_device(openinpresentation=1, devicewidth=120.)

# === SAVE ===
patch.save("m4l_filter_device.amxd", device_type="audio_effect")
