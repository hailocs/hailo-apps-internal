#!/usr/bin/env python3
"""
Test script for ONNX postprocessing modes.
Runs detection with both HEF+ONNX-postproc and Full-ONNX modes and saves outputs.
"""

import os
import sys
import json
import subprocess
import shutil
from pathlib import Path


def run_detection_mode(mode_name, use_full_onnx, config_path, hef_path, input_image, output_dir):
    """
    Run object detection in specified mode and save output.
    
    Args:
        mode_name: Descriptive name for the mode
        use_full_onnx: True for full ONNX mode, False for HEF+ONNX postproc
        config_path: Path to ONNX config file
        hef_path: Path to HEF model
        input_image: Path to input image
        output_dir: Directory to save output
    """
    
    print(f"\n{'='*80}")
    print(f"Running: {mode_name}")
    print(f"{'='*80}")
    
    # Create temporary config with appropriate mode setting
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    config['use_full_onnx_mode'] = use_full_onnx
    
    temp_config = config_path.replace('.json', f'_temp.json')
    with open(temp_config, 'w') as f:
        json.dump(config, f, indent=2)
    
    print(f"Created temp config: {temp_config}")
    print(f"  use_full_onnx_mode = {config['use_full_onnx_mode']}")
    
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Build command
    cmd = [
        sys.executable,
        'object_detection.py',
        '-n', hef_path,
        '-i', input_image,
        '--onnxconfig', temp_config,
        '--save-output',
        '--output-dir', output_dir
    ]
    
    print(f"Running: {' '.join(cmd)}\n")
    
    # Run detection
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        # Parse detection counts from output
        num_detections = 0
        class_0_count = 0
        class_5_count = 0
        seen_raw_bbox = False
        
        # Show relevant output and count detections
        for line in result.stdout.split('\\n'):
            if any(keyword in line for keyword in ['INFO', 'SUCCESS', 'ERROR', 'Full ONNX', 'dequantized', 'Loaded', 'Saved', 'DEBUG', '>>>', '===', 'routing', 'Routing', 'Class']):
                print(line)
            
            # Count detections from debug output (only from "Raw bbox" lines to avoid double-counting)
            if 'Total detections after threshold' in line:
                try:
                    num_detections = int(line.split(':')[-1].strip())
                except:
                    pass
            if 'Raw bbox' in line:
                if 'Class 0, Score:' in line:
                    class_0_count += 1
                if 'Class 5, Score:' in line:
                    class_5_count += 1
        
        success = result.returncode == 0
        
        # Output should already be in output_dir from --output-dir flag
        output_image = Path(output_dir) / 'output_0.png'
        
        # Validate detections for Full ONNX mode
        detection_valid = True
        if 'Full ONNX' in mode_name:
            if num_detections != 5:
                detection_valid = False
                print(f"\n⚠️  Expected 5 detections, got {num_detections}")
            if class_0_count != 4:
                detection_valid = False
                print(f"\n⚠️  Expected 4 people (class 0), got {class_0_count}")
            if class_5_count != 1:
                detection_valid = False
                print(f"\n⚠️  Expected 1 bus (class 5), got {class_5_count}")
        
        if success and detection_valid:
            print(f"\n✅ {mode_name} completed successfully")
            print(f"   Detections: {num_detections} total (class 0: {class_0_count}, class 5: {class_5_count})")
            if output_image.exists():
                print(f"   Output saved: {output_image}")
            else:
                print(f"   ⚠️  Expected output not found: {output_image}")
                # List what's actually in the directory
                files = list(Path(output_dir).glob('*'))
                if files:
                    print(f"   Files in {output_dir}: {[f.name for f in files]}")
                success = False
        elif not detection_valid:
            print(f"\n❌ {mode_name} failed: Detection validation failed")
            success = False
        else:
            print(f"\n❌ {mode_name} failed (exit code: {result.returncode})")
            if result.stderr:
                print(f"   Error: {result.stderr[:200]}")
        
        return success, str(output_image) if output_image.exists() else None
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False, None
    
    finally:
        # Cleanup temp config
        if os.path.exists(temp_config):
            os.remove(temp_config)


def main():
    """Run tests for both ONNX postprocessing modes."""
    
    print("\n" + "="*80)
    print("ONNX Postprocessing Test Script")
    print("Compares HEF+ONNX-Postproc vs Full-ONNX modes")
    print("="*80)
    
    # Configuration
    config_path = 'config_onnx_yolo26n.json'
    hef_path = '/usr/local/hailo/resources/models/hailo8/yolo26n.hef'
    input_image = 'bus.jpg'
    
    # Validate inputs
    for path, name in [(config_path, "Config"), (hef_path, "HEF")]: #, (input_image, "Image")]:
        if not os.path.exists(path):
            print(f"❌ {name} not found: {path}")
            return 1
    
    print(f"\nTest Configuration:")
    print(f"  Config:  {config_path}")
    print(f"  HEF:     {hef_path}")
    print(f"  Input:   {input_image}")
    
    # Test both modes
    results = {}
    
    # Mode 1: HEF + ONNX Postprocessing (standard mode)
    success, output_path = run_detection_mode(
        mode_name="HEF + ONNX Postprocessing",
        use_full_onnx=False,
        config_path=config_path,
        hef_path=hef_path,
        input_image=input_image,
        output_dir="output_hef_onnx"
    )
    results['hef_onnx'] = {'success': success, 'output_path': output_path}
    
    # Mode 2: Full ONNX (debug mode - bypasses HEF)
    success, output_path = run_detection_mode(
        mode_name="Full ONNX (Debug Mode)",
        use_full_onnx=True,
        config_path=config_path,
        hef_path=hef_path,
        input_image=input_image,
        output_dir="output_full_onnx"
    )
    results['full_onnx'] = {'success': success, 'output_path': output_path}
    
    # Summary
    print(f"\n{'='*80}")
    print("Test Summary")
    print(f"{'='*80}")
    
    print(f"\n1. HEF + ONNX Postprocessing: {'✅ PASS' if results['hef_onnx']['success'] else '❌ FAIL'}")
    if results['hef_onnx']['output_path']:
        print(f"   Output: {results['hef_onnx']['output_path']}")
    
    print(f"\n2. Full ONNX (Debug Mode):    {'✅ PASS' if results['full_onnx']['success'] else '❌ FAIL'}")
    if results['full_onnx']['output_path']:
        print(f"   Output: {results['full_onnx']['output_path']}")
    
    print(f"\n{'='*80}")
    print("How ONNX Postprocessing Works:")
    print(f"{'='*80}")
    print("""
Mode 1: HEF + ONNX Postprocessing (Recommended)
  • Runs inference on Hailo hardware (HEF)
  • HEF outputs are dequantized to FLOAT32
  • ONNX postprocessing model processes HEF outputs
  • Produces final detections

Mode 2: Full ONNX (Debug/Testing Only)
  • Bypasses Hailo hardware completely
  • Runs entire model inference in ONNX
  • Useful for validating postprocessing without hardware
  • Slower than HEF mode

Both modes should produce similar detection results.
Compare the output images to verify consistency.
""")
    
    return 0 if all(r['success'] for r in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())

