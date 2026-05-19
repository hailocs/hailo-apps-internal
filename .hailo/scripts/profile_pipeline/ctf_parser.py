#!/usr/bin/env python3
"""
Custom CTF 1.8 binary parser for GST-Shark traces.

Parses the binary trace format directly, avoiding babeltrace2 version mismatch issues.
Reads the `metadata` text file to dynamically detect event IDs and field layouts,
then parses the `datastream` binary file accordingly.

Usage:
    python ctf_parser.py <trace_dir>
"""

import os
import re
import struct
import sys
from pathlib import Path


# --- Metadata Parser ---

# Field type specs
FIELD_UINT32 = {"type": "uint", "size": 4, "fmt": "<I"}
FIELD_UINT64 = {"type": "uint", "size": 8, "fmt": "<Q"}
FIELD_FLOAT32 = {"type": "float", "size": 4, "fmt": "<f"}
FIELD_STRING = {"type": "string", "size": None, "fmt": None}


def parse_metadata(metadata_path):
    """Parse the CTF metadata text file to extract event definitions.

    Returns:
        dict: event_id -> {"name": str, "fields": list[{"name": str, **field_spec}]}
    """
    text = Path(metadata_path).read_text()

    # Extract UUID from trace block
    uuid_match = re.search(r'trace\s*\{[^}]*uuid\s*=\s*"([^"]+)"', text, re.DOTALL)
    trace_uuid = uuid_match.group(1) if uuid_match else None

    # Extract clock frequency
    freq_match = re.search(r'freq\s*=\s*(\d+)', text)
    clock_freq = int(freq_match.group(1)) if freq_match else 1000000

    # Parse event blocks — use a two-pass approach to handle nested braces
    events = {}
    # First find each event { ... } block by brace counting
    event_start_pattern = re.compile(r'event\s*\{')
    for m in event_start_pattern.finditer(text):
        start = m.end()
        depth = 1
        pos = start
        while pos < len(text) and depth > 0:
            if text[pos] == '{':
                depth += 1
            elif text[pos] == '}':
                depth -= 1
            pos += 1
        block = text[start:pos - 1]

        name_m = re.search(r'name\s*=\s*(\w+)', block)
        id_m = re.search(r'id\s*=\s*(\d+)', block)
        if not name_m or not id_m:
            continue

        name = name_m.group(1)
        event_id = int(id_m.group(1))

        # Extract fields block if present
        fields = []
        fields_m = re.search(r'fields\s*:=\s*struct\s*\{', block)
        if fields_m:
            fstart = fields_m.end()
            fdepth = 1
            fpos = fstart
            while fpos < len(block) and fdepth > 0:
                if block[fpos] == '{':
                    fdepth += 1
                elif block[fpos] == '}':
                    fdepth -= 1
                fpos += 1
            fields_block = block[fstart:fpos - 1]
            fields = _parse_fields(fields_block)

        events[event_id] = {"name": name, "fields": fields}

    # Count CPU fields in cpuusage event (if present)
    for eid, edef in events.items():
        if edef["name"] == "cpuusage":
            edef["num_cpus"] = len(edef["fields"])

    return {
        "uuid": trace_uuid,
        "clock_freq": clock_freq,
        "events": events,
    }


def _parse_fields(fields_block):
    """Parse the fields block of an event definition."""
    fields = []

    # Match string fields
    # Match integer fields: integer { size = N; ... } name;
    # Match floating_point fields: floating_point { ... } name;
    field_pattern = re.compile(
        r'(?:'
        r'string\s+(\w+)'                                          # string field
        r'|integer\s*\{[^}]*size\s*=\s*(\d+)[^}]*\}\s*(\w+)'     # integer field
        r'|floating_point\s*\{[^}]*\}\s*(\w+)'                    # float field
        r')\s*;',
        re.DOTALL
    )

    for fm in field_pattern.finditer(fields_block):
        if fm.group(1):  # string
            fields.append({"name": fm.group(1), **FIELD_STRING})
        elif fm.group(2):  # integer
            size_bits = int(fm.group(2))
            name = fm.group(3)
            if size_bits == 64:
                fields.append({"name": name, **FIELD_UINT64})
            elif size_bits == 32:
                fields.append({"name": name, **FIELD_UINT32})
            elif size_bits == 16:
                fields.append({"name": name, "type": "uint", "size": 2, "fmt": "<H"})
            elif size_bits == 8:
                fields.append({"name": name, "type": "uint", "size": 1, "fmt": "<B"})
        elif fm.group(4):  # float
            fields.append({"name": fm.group(4), **FIELD_FLOAT32})

    return fields


# --- Binary Parser ---

def _read_string(data, offset):
    """Read a null-terminated string from binary data."""
    end = data.index(b'\x00', offset)
    return data[offset:end].decode('utf-8', errors='replace'), end + 1


def parse_trace(trace_dir):
    """Parse a GST-Shark CTF trace directory.

    Args:
        trace_dir: Path to directory containing `metadata` and `datastream` files.
                   Also checks for `channel0_0/` subdirectory.

    Returns:
        dict with keys:
            "metadata": parsed metadata info
            "events": dict[event_name] -> list[dict] with event fields + "timestamp"
    """
    trace_dir = Path(trace_dir)

    # Find metadata file
    metadata_path = trace_dir / "metadata"
    if not metadata_path.exists():
        raise FileNotFoundError(f"No metadata file in {trace_dir}")

    meta = parse_metadata(metadata_path)

    # Find datastream file (may be in channel0_0/ subdirectory)
    datastream_path = trace_dir / "datastream"
    if not datastream_path.exists():
        channel_dir = trace_dir / "channel0_0"
        if channel_dir.exists():
            datastream_path = channel_dir / "datastream"
    if not datastream_path.exists():
        raise FileNotFoundError(f"No datastream file in {trace_dir}")

    data = datastream_path.read_bytes()
    events_by_type = {edef["name"]: [] for edef in meta["events"].values()}

    offset = _parse_datastream(data, meta, events_by_type)

    return {
        "metadata": meta,
        "events": events_by_type,
    }


def _parse_datastream(data, meta, events_by_type):
    """Parse the binary datastream."""
    offset = 0
    data_len = len(data)
    event_defs = meta["events"]
    clock_freq = meta["clock_freq"]

    # Parse packet header
    if data_len < 24:
        return offset

    magic = struct.unpack_from("<I", data, offset)[0]
    offset += 4
    if magic != 0xC1FC1FC1:
        raise ValueError(f"Invalid magic: 0x{magic:08X}")

    # Skip UUID (16 bytes) and stream_id (4 bytes)
    offset += 20

    # Parse packet context
    timestamp_begin = struct.unpack_from("<Q", data, offset)[0]
    offset += 8
    timestamp_end = struct.unpack_from("<Q", data, offset)[0]
    offset += 8

    # Parse events
    while offset < data_len:
        try:
            offset = _parse_event(data, offset, data_len, event_defs, events_by_type, clock_freq)
        except (struct.error, IndexError, ValueError):
            break

    return offset


def _parse_event(data, offset, data_len, event_defs, events_by_type, clock_freq):
    """Parse a single event from the datastream."""
    if offset + 2 > data_len:
        raise ValueError("Not enough data for event header")

    event_id_raw = struct.unpack_from("<H", data, offset)[0]
    offset += 2

    if event_id_raw == 0xFFFF:
        # Extended header
        if offset + 12 > data_len:
            raise ValueError("Not enough data for extended header")
        event_id = struct.unpack_from("<I", data, offset)[0]
        offset += 4
        timestamp = struct.unpack_from("<Q", data, offset)[0]
        offset += 8
    else:
        # Compact header
        event_id = event_id_raw
        if offset + 4 > data_len:
            raise ValueError("Not enough data for compact header")
        timestamp = struct.unpack_from("<I", data, offset)[0]
        offset += 4

    # Look up event definition
    if event_id not in event_defs:
        raise ValueError(f"Unknown event id: {event_id}")

    edef = event_defs[event_id]
    event_name = edef["name"]

    # Parse fields
    record = {"timestamp": timestamp, "timestamp_s": timestamp / clock_freq}
    for field in edef["fields"]:
        if field["type"] == "string":
            val, offset = _read_string(data, offset)
            record[field["name"]] = val
        else:
            if offset + field["size"] > data_len:
                raise ValueError("Not enough data for field")
            val = struct.unpack_from(field["fmt"], data, offset)[0]
            offset += field["size"]
            record[field["name"]] = val

    events_by_type[event_name].append(record)
    return offset


# --- CLI ---

def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <trace_dir>")
        sys.exit(1)

    trace_dir = sys.argv[1]
    result = parse_trace(trace_dir)

    print(f"Trace UUID: {result['metadata']['uuid']}")
    print(f"Clock frequency: {result['metadata']['clock_freq']} Hz")
    print(f"\nEvent counts:")
    for name, events in result["events"].items():
        print(f"  {name}: {len(events)}")

    # Print sample events
    for name, events in result["events"].items():
        if events:
            print(f"\n--- {name} (first 3) ---")
            for ev in events[:3]:
                # Print without timestamp_s for brevity
                display = {k: v for k, v in ev.items() if k != "timestamp_s"}
                print(f"  {display}")


if __name__ == "__main__":
    main()
