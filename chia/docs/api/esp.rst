ESP Support
===========

CHIA drives `ESP <https://esp.cs.columbia.edu>`_ (Embedded Scalable
Platforms, Columbia SLD) flows through :mod:`chia.esp`. Every ESP flow is a
``make`` target run from a per-board working directory; a single
:class:`~chia.esp.esp_workspace.EspWorkspaceNode` models one such workspace,
with a typed member per flow (``configure``, ``build``, ``sim``, ``accgen``,
``accel``, ``synth``, ``fpga_program``, ``fpga_run``) plus generic
primitives (``make`` / ``put_file`` / ``remove`` / ``collect``). All members
share one placement so the path-based state a flow leaves behind is visible
to the next.

The notes below cover what a worker needs to run these flows correctly; the
:ref:`api reference <esp-api-reference>` follows.

The worker
----------

An ESP worker is built on ESP's own container image, which supplies the OS
dependencies, the RISC-V / SPARC cross-toolchains, and the socgen Python
environment; CHIA is layered on top as a self-contained interpreter. Two
consequences shape how everything else is set up:

- **No CAD tools live in the image.** Simulation, HLS, and bitstream flows
  need the host's tool installs bind-mounted into the container, with the
  matching license environment variables set. Only the license-free flows
  (configuration, software builds, the RTL accelerator flow) run with no
  mounts at all — a good first target when validating a new worker.
- **socgen needs the image's Python, not CHIA's.** ESP's ``socgen`` relies
  on pre-3.10 ``tkinter`` behavior (plus ``Pmw``), so ``configure`` runs in
  the container even when other stages run elsewhere. Do not expect it to
  work against the CHIA interpreter.

Keep site-specific values — hostnames, install paths, license servers — out
of committed cluster configuration. Parameterize the configuration with
environment variables resolved at load time, and source the real values
from an uncommitted file, so the configuration itself stays portable.

Simulation
----------

``sim`` runs a full-SoC RTL simulation. The worker needs the simulator (and,
once per checkout, Vivado to compile the vendor simulation libraries) bind-
mounted with its license environment. Three things that commonly trip a
first run:

- Point ``XILINX_VIVADO`` at the real Vivado install root. ESP's image
  stubs it, which mangles the paths the simulation flow compiles.
- Judge success by a transcript match, not exit code — an RTL simulation
  can exit cleanly without the program passing. ``sim`` takes a
  ``pass_pattern`` for this (ESP's testbench prints a fixed end-of-run
  message).
- After reconfiguring the SoC, run ``sim(clean=True)`` once. The
  simulator's incremental rebuild fails on units compiled against the
  previous SoC map.

Vivado and the FPGA flow
------------------------

.. important::

   **If you plan to run Vivado, keep the ESP checkout on the host and bind-
   mount it into the container, rather than synthesizing inside the
   container.** Vivado's multi-process synthesis (notably the DDR4 memory-
   controller IP) hangs inside ESP's older container userland. The reliable
   arrangement:

   - Keep the ESP checkout on the host and bind-mount it into the worker
     container at the **identical path**. Vivado writes absolute paths into
     its project, so the host and the container must agree on where the
     workspace lives; pass that path as ``esp_root`` to every member.
   - Run ``synth`` on a worker that has Vivado and the host userland (a bare
     host worker, e.g. the cluster head), separate from the container that
     runs ``configure`` and ``build``. Because both see the one shared
     workspace, they cooperate on the same tree — the container compiles the
     software and generates the RTL, the host synthesizes it.

Other FPGA-flow facts worth knowing:

- **Vendor IP versions are pinned per board.** ESP pins exact Xilinx IP
  versions in its board constraints. A Vivado whose catalog has moved on
  fails at IP creation; adjust the pin in your checkout, or synthesize with
  an era-matched Vivado. No single value suits every Vivado release.
- **Match the hw_server version.** Programming connects a Vivado client to
  a ``hw_server`` on the machine holding the JTAG cable, and the server only
  accepts clients at or below its own version. ``synth`` and
  ``fpga_program`` each take a ``vivado_bin`` override, so you can
  synthesize with one Vivado and program with an older, server-compatible
  one.
- **Programming is fully networked.** ``fpga_program`` reaches ``hw_server``
  over TCP; the worker needs reachability to it (a direct route or a
  tunnel), never the cable itself.
- **The run leg is EDCL over UDP.** ``fpga_run`` loads the SoC over its
  Ethernet via ESPLink, so the worker needs a UDP route to the board's IP
  (set in the SoC configuration). If that UDP is relayed, note that ESP's
  EDCL only answers requests whose source port is the ESPLink port (a relay
  must preserve it), and that UDP cannot ride an SSH tunnel — a point-to-
  point board segment needs a relay on the cabled host or a scoped firewall
  opening.
- **The console is read over TCP.** ``fpga_run`` scrapes a TCP-exposed
  serial port for its ``pass_pattern``. Identify which serial channel is the
  console, and at what baud, for your board.

Resources as license seats
---------------------------

CHIA models tool licenses and scarce hardware as Ray resources, so the
scheduler does admission control instead of letting tools fail at checkout.
Advertise capacity on the workers that can satisfy each, and give members
the matching demand:

===============  ======================================================
Resource         Held by / meaning
===============  ======================================================
``esp``          any ESP-capable worker (config, software, RTL flow)
``esp_xcelium``  simulator seats — capacity = concurrent sims admitted
``esp_vivado``   Vivado synthesis seats (advertise on the host worker)
``esp_fpga``     an attached board — capacity 1 serializes access
===============  ======================================================

.. _esp-api-reference:

API reference
-------------

Generated from the source docstrings, so it stays in sync with the code.

State definitions
~~~~~~~~~~~~~~~~~~

.. automodule:: chia.esp.state_def

Workspace node
~~~~~~~~~~~~~~~

.. automodule:: chia.esp.esp_workspace
