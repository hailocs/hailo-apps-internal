# Debugging GStreamer Pipelines with GstShark

GstShark is a powerful profiling and debugging tool for GStreamer pipelines. It provides "tracers" that extract data from the pipeline in real-time, allowing you to monitor queue levels, latency, framerate, and CPU usage per element.

## 1. Installation

### Prerequisites

Install the required build tools and GStreamer development libraries.

**On Ubuntu / Debian / Raspberry Pi OS:**

```bash
sudo apt-get update
sudo apt-get install -y \
    git \
    libgstreamer1.0-dev \
    libgstreamer-plugins-base1.0-dev \
    libgstreamer-plugins-bad1.0-dev \
    autoconf \
    automake \
    libtool \
    graphviz \
    pkg-config \
    gtk-doc-tools
```

### Build and Install

We will build `gst-shark` from source.

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/RidgeRun/gst-shark.git
    cd gst-shark
    ```

2.  **Configure:**
    You must specify the correct library directory.

    *   **For x86_64 PCs (Standard Ubuntu):**
        ```bash
        ./autogen.sh --prefix=/usr/ --libdir=/usr/lib/x86_64-linux-gnu/gstreamer-1.0/
        ```

    *   **For Raspberry Pi 5 (aarch64 / Debian Trixie):**
        ```bash
        ./autogen.sh --prefix=/usr/ --libdir=/usr/lib/aarch64-linux-gnu/gstreamer-1.0/
        ```

    *   *Tip: If you are unsure of your architecture, run `uname -m`. `x86_64` uses the first command, `aarch64` uses the second.*

3.  **Compile and Install:**
    ```bash
    make
    sudo make install
    ```

### Verify Installation

Check if GStreamer can see the new tracers:

```bash
gst-inspect-1.0 sharktracers
```

You should see a list of tracers including `interlatency`, `proctime`, `framerate`, `queuelevel`, etc.

---

## 2. Real-Time Debugging (Console Output)

You can print trace information directly to the console to debug bottlenecks live.

### Monitoring Queue Levels

This is critical for diagnosing "stuck" pipelines or jitter.

```bash
GST_DEBUG="GST_TRACER:7" GST_TRACERS="queuelevel" python3 your_app.py
```

**What to look for:**
*   **Bottleneck:** Queue level hits max (e.g., `30/30`) and stays there. The element *reading* from this queue is too slow.
*   **Starvation:** Queue level is always 0. The element *feeding* this queue is too slow.

### Other Useful Tracers

*   **Latency Spikes:** `GST_TRACERS="interlatency"`
*   **Throughput:** `GST_TRACERS="framerate"`
*   **Processing Time:** `GST_TRACERS="proctime"`

---

## 3. Generating Graphical Plots

GstShark can record pipeline data to a folder and generate professional charts (PDF/PNG) showing behavior over time. This is excellent for post-mortem analysis.

### Step 1: Install Plotting Dependencies

The plotting scripts require Octave and Gnuplot.

```bash
sudo apt-get install -y octave gnuplot ghostscript
```

### Step 2: Record the Trace Data

Run your application with `GST_SHARK_LOCATION` set. This tells GstShark where to save the data.

```bash
# Create a directory for the trace logs
mkdir -p trace_data

# Run the app with desired tracers
GST_DEBUG="GST_TRACER:7" \
GST_TRACERS="proctime;interlatency;framerate;scheduletime;cpuusage;queuelevel" \
GST_SHARK_LOCATION=trace_data \
python3 your_app.py
```

*   Run the app for at least 10-20 seconds to gather meaningful data.
*   Stop the app (Ctrl+C).
*   You will see a folder `trace_data` containing a CTF (Common Trace Format) metadata file and binary logs.

### Step 3: Generate the Charts

Use the `gstshark-plot` script located in the `gst-shark` source directory you cloned earlier.

```bash
# Assuming you are in the directory where you cloned gst-shark
./gst-shark/scripts/graphics/gstshark-plot trace_data
```

This will analyze the logs and generate PDF charts inside the `trace_data` directory.

### Step 4: Analyze the Results

Open the generated PDFs:

*   **`queuelevel.pdf`**: Shows the buffer count in every queue over time. Look for lines that plateau at the top (full) or bottom (empty).
*   **`framerate.pdf`**: Shows the FPS at various points. Look for drops.
*   **`cpuusage.pdf`**: Shows CPU load per element.
*   **`proctime.pdf`**: Shows how long each element takes to process a buffer. This helps identify the slowest specific element (e.g., is it the inference engine, the post-process, or the display?).

---

## 4. External Documentation

For deeper details on interpreting every metric, refer to the official documentation:

*   **GstShark Wiki:** [https://developer.ridgerun.com/wiki/index.php?title=GstShark](https://developer.ridgerun.com/wiki/index.php?title=GstShark)
*   **GstShark GitHub:** [https://github.com/RidgeRun/gst-shark](https://github.com/RidgeRun/gst-shark)
