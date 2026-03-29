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


def run_detection_mode(mode_name, use_debug_ref_onnx, config_path, hef_path, input_image, output_dir, neural_onnx_ref=None):
    """
    Run object detection in specified mode and save output.
    
    Args:
        mode_name: Descriptive name for the mode
        use_debug_ref_onnx: True for debug reference ONNX mode, False for HEF+ONNX postproc
        config_path: Path to ONNX config file
        hef_path: Path to HEF model
        input_image: Path to input image
        output_dir: Directory to save output
    """
    
    print(f"\n{'='*80}")
    print(f"Running: {mode_name}")
    print(f"{'='*80}")
    
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Build command for requested mode
    cmd = [
        sys.executable,
        'object_detection.py',  # In parent directory
        '-n', hef_path,
        '-i', input_image,
        '--onnxconfig', config_path,
        '--save-output',
        '--output-dir', output_dir
    ]
    
    # Add debug reference ONNX if needed
    if use_debug_ref_onnx:
        if not neural_onnx_ref:
            raise ValueError("Debug reference ONNX mode requires neural_onnx_ref path")
        cmd.extend(['--neural-onnx-ref', neural_onnx_ref])
    
    print(f"Running: {' '.join(cmd)}\n")
    
    # Run detection
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        # Show relevant output
        for line in result.stdout.split('\n'):
            if any(keyword in line for keyword in ['INFO', 'SUCCESS', 'ERROR', 'Full ONNX', 'dequantized', 'Loaded', 'Saved', 'DEBUG', '>>>', '===', 'routing', 'Routing']):
                print(line)
        
        success = result.returncode == 0
        
        # Move output from default '../output/' to our output_dir
        default_output = Path('output') / 'output_0.png'
        target_output = Path(output_dir) / 'output_0.png'
        
        if default_output.exists():
            shutil.copy(default_output, target_output)
            print(f"   Copied output from {default_output} to {target_output}")
        
        # Check for output_0.png (default output filename for images)
        output_image = target_output
        
        if success:
            print(f"\n✅ {mode_name} completed successfully")
            if output_image.exists():
                print(f"   Output saved: {output_image}")
            else:
                print(f"   ⚠️  Expected output not found: {output_image}")
                # List what's actually in the directory
                files = list(Path(output_dir).glob('*'))
                if files:
                    print(f"   Files in {output_dir}: {[f.name for f in files]}")
        else:
            print(f"\n❌ {mode_name} failed (exit code: {result.returncode})")
            if result.stderr:
                print(f"   Error: {result.stderr[:200]}")
        
        return success, str(output_image) if output_image.exists() else None
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False, None


def main():
    """Run tests for both ONNX postprocessing modes."""
    
    print("\n" + "="*80)
    print("ONNX Postprocessing Test Script")
    print("Compares HEF+ONNX-Postproc vs Full-ONNX modes")
    print("="*80)
    
    # Configuration
    config_path = 'onnx/config_onnx_yolo26n.json' 
    hef_path = '/usr/local/hailo/resources/models/hailo8/yolo26n.hef'
    input_image = 'bus.jpg'
    neural_onnx_ref = 'onnx/yolo26n_neural_processing.onnx'
    
    # Validate inputs
    for path, name in [(config_path, "Config"), (hef_path, "HEF")]: #, (input_image, "Image")]:
        if not os.path.exists(path):
            print(f"❌ {name} not found: {path}")
            return 1
    
    print(f"\nTest Configuration:")
    print(f"  Config:  {config_path}")
    print(f"  HEF:     {hef_path}")
    print(f"  Input:   {input_image}")
    print(f"  Neural ONNX ref (debug): {neural_onnx_ref}")
    
    # Test both modes
    results = {}
    
    # Mode 1: HEF + ONNX Postprocessing (standard mode)
    success, output_path = run_detection_mode(
        mode_name="HEF + ONNX Postprocessing",
        use_debug_ref_onnx=False,
        config_path=config_path,
        hef_path=hef_path,
        input_image=input_image,
        output_dir="onnx/output_hef_onnx"  # In parent directory
    )
    results['hef_onnx'] = {'success': success, 'output_path': output_path}
    
    # Mode 2: Full ONNX (debug mode - bypasses HEF)
    success, output_path = run_detection_mode(
        mode_name="Full ONNX (Debug Mode)",
        use_debug_ref_onnx=True,
        config_path=config_path,
        hef_path=hef_path,
        input_image=input_image,
        output_dir="onnx/output_debug_ref_onnx",  # In parent directory
        neural_onnx_ref=neural_onnx_ref,
    )
    results['debug_ref_onnx'] = {'success': success, 'output_path': output_path}
    
    # Summary
    print(f"\n{'='*80}")
    print("Test Summary")
    print(f"{'='*80}")
    
    print(f"\n1. HEF + ONNX Postprocessing: {'✅ PASS' if results['hef_onnx']['success'] else '❌ FAIL'}")
    if results['hef_onnx']['output_path']:
        print(f"   Output: {results['hef_onnx']['output_path']}")
    
    print(f"\n2. Debug Reference ONNX:      {'✅ PASS' if results['debug_ref_onnx']['success'] else '❌ FAIL'}")
    if results['debug_ref_onnx']['output_path']:
        print(f"   Output: {results['debug_ref_onnx']['output_path']}")
    
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

