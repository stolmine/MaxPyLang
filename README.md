# MaxPyLang

[![CI](https://github.com/Barnard-PL-Labs/MaxPy-Lang/actions/workflows/ci.yml/badge.svg)](https://github.com/Barnard-PL-Labs/MaxPy-Lang/actions/workflows/ci.yml)

MaxPyLang is a Python package for metaprogramming of MaxMSP that uses Python to generate and edit Max patches. MaxPyLang allows users to move freely between text-based Python programming and visual programming in Max, making it much easier to implement dynamic patches, random patches, mass-placement and mass-connection of objects, and other easily text-programmed techniques.

As a text-based interface to MaxMSP, MaxPyLang enables vibecoding of Max patches. Provide an example to your tool of choice (Claude code, Cursor, etc), and ask for the patch you would like. Tutorial coming soon.

## Installation

We publish our package on Pypi as [MaxPyLang](https://pypi.org/project/maxpylang/). It is easiest to install from there.

```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install maxpylang
```

## Documentation
- [Full Documentation](https://barnard-pl-labs.github.io/MaxPyLang/)
- [API Reference](https://barnard-pl-labs.github.io/MaxPyLang/API/API.html)
- [Examples](https://github.com/Barnard-PL-Labs/MaxPyLang/tree/main/examples)
- [Tutorials](https://barnard-pl-labs.github.io/MaxPyLang/tutorial.html)

## Quick Start

See this example in [examples/hello_world](./examples/hello_world).
To run this, `python3 examples/hello_world/main.py` will create a Max patch file `hello_world.maxpat` that contains a simple audio oscillator connected to the DAC.
You can then open this patch in MaxMSP and click the DAC to hear a 440 Hz tone.

```python
import maxpylang as mp

patch = mp.MaxPatch()
osc = patch.place("cycle~ 440")[0]
dac = patch.place("ezdac~")[0]
patch.connect([osc.outs[0], dac.ins[0]])
patch.save("hello_world.maxpat")
```

## Max for Live Devices

Patches can be saved as Ableton Live devices (`.amxd`). The `live.*` objects
(`live.dial`, `live.text`, `live.gain~`, `live.object`, `live.thisdevice`, ...) are bundled,
and Live parameter properties are plain keyword attributes:

```python
import maxpylang as mp

patch = mp.MaxPatch()
plugin = patch.place("plugin~")[0]
filt = patch.place("lores~ 1000 0.3")[0]
plugout = patch.place("plugout~")[0]

cutoff = patch.place(mp.MaxObject(
    "live.dial", parameter_longname="Cutoff",
    parameter_mmin=20., parameter_mmax=20000., parameter_initial=1000.,
    parameter_unitstyle="hertz", parameter_exponent=3.))[0]
cutoff.present(8, 8)                      # show it in the device view

patch.connect([plugin.outs[0], filt.ins[0]], [cutoff.outs[0], filt.ins[1]],
              [filt.outs[0], plugout.ins[0]], [filt.outs[0], plugout.ins[1]])
patch.set_device(openinpresentation=1)    # Live shows the presentation view
patch.save("filter.amxd", device_type="audio_effect")
```

See [examples/m4l_filter_device](./examples/m4l_filter_device) for a complete stereo device.
The `live.*` object database is generated offline from an Ableton Live 12 install with
`python -m maxpylang.import_m4l`.

## Reading existing devices

MaxPyLang can open and explain existing Max for Live devices, including frozen
devices (dependencies bundled inside the `.amxd`) and older devices without a
`meta` chunk. Reading never modifies the device. Ableton-encrypted devices
(the built-in MIDI Tools, for example) are detected and reported as
"encrypted device — cannot be read".

```bash
maxpylang survey "~/Music/M4L devices"      # one line per device: type, #params, frozen/encrypted, size
maxpylang describe "Device.amxd"            # Markdown: parameters, device view, signal flow, structure, code
maxpylang describe "Device.amxd" --json     # everything, including the full object graph
maxpylang describe "Device.amxd" --depth 5 --full-code
maxpylang params "Device.amxd"              # every Live parameter, with what it controls
maxpylang extract "Device.amxd" out/        # main patch as out/Device.maxpat + embedded files
```

`describe` lists each Live parameter (name, type, range, unit, exponent, enum
items, modulation mode, whether it is in the device view) and traces a few hops
downstream through cords, subpatchers and send/receive pairs to show which DSP
objects it controls. It also shows the audio path from `plugin~` to `plugout~`,
the MIDI path, the subpatcher/abstraction hierarchy, the device view
top-to-bottom, patcher comments and embedded js/gen code.

The same tools from Python:

```python
d = mp.describe("Device.amxd")
print(d.to_markdown())
data = d.to_json()
mp.extract("Device.amxd", "out")
rows = list(mp.survey("M4L devices"))
patch = mp.MaxPatch(load_file="Device.amxd")   # frozen devices load too
```

## Citation

MaxPy was published as a [demo paper](examples/NIME2023/MaxPy-NIME-2023-Paper.pdf) for NIME 2023.
The package name was updated to MaxPyLang in 2025 to avoid confusion with other similarly named packages.


## Watch MaxPyLang in Action

We post demos, tutorials, and generated patch examples on our YouTube channel:  
-> https://youtube.com/@fishpyler

## Video Demos

### Simple Demo of Jitter Patch
[![Simple Demo of Jitter Patch](https://img.youtube.com/vi/rMhSA1ZN5Mg/0.jpg)](https://www.youtube.com/watch?v=rMhSA1ZN5Mg)

A demo showing MaxPyLang generating a Jitter patch programmatically, demonstrating dynamic patch creation and integration with visual systems.

### Generating Your First Max Patch with Python
[![First MaxPatch Generation](https://img.youtube.com/vi/e5arn3SkfJI/0.jpg)](https://www.youtube.com/watch?v=e5arn3SkfJI)

Walkthrough of generating a basic Max patch using Python, including object placement and connections.


More videos (including tutorials and advanced examples) coming soon!


## Older Video Demos 
### [Basics](https://www.youtube.com/watch?v=F8Fpe0Udc4M)      
[![Introduction to MaxPy](https://img.youtube.com/vi/F8Fpe0Udc4M/0.jpg)](https://www.youtube.com/watch?v=F8Fpe0Udc4M)     
Mark demonstrates the basics of installing MaxPy, creating patches, and placing objects.   
<br>
### [Variable-Oscillator Synth](https://www.youtube.com/watch?v=nxusu32kkxs)       
[![Variable-Oscillator Synth Explanation](https://img.youtube.com/vi/nxusu32kkxs/0.jpg)](https://www.youtube.com/watch?v=nxusu32kkxs)      
Ranger explains a MaxPy script that dynamically generates an additive synth with a variable number of oscillators. The code for this synth is under [examples/variable-osc-synth](examples/variable-osc-synth). 
<br>
### [Replace() function]((https://youtu.be/RgYRqXn8Z6o))       
[![Using Replace() function with MaxPy](https://img.youtube.com/vi/RgYRqXn8Z6o/0.jpg)](https://youtu.be/RgYRqXn8Z6o)      
Satch explains using the replace() function to selectively replace objects in a loaded patch to sonify stock data. The code for this is under [examples/stocksonification_v1](examples/stocksonification_v1). 
