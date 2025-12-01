#!/usr/bin/env python3
"""
Simple script to verify that all configuration files can be loaded correctly.
This doesn't require pytest or other test dependencies.
"""

import yaml
from pathlib import Path

def verify_configs():
    """Verify all configuration files can be loaded."""
    print("=" * 80)
    print("VERIFYING CONFIGURATION FILES")
    print("=" * 80)
    
    # Test control config
    control_path = Path(__file__).parent / "test_control.yaml"
    print(f"\n1. Loading test_control.yaml from: {control_path}")
    if not control_path.exists():
        print(f"   ❌ File not found!")
        return False
    with open(control_path, 'r') as f:
        control = yaml.safe_load(f)
    print(f"   ✓ Loaded successfully")
    print(f"   Keys: {list(control.keys())}")
    
    # Test definition config
    definition_path = Path(__file__).parent.parent / "hailo_apps" / "config" / "test_definition_config.yaml"
    print(f"\n2. Loading test_definition_config.yaml from: {definition_path}")
    if not definition_path.exists():
        print(f"   ❌ File not found!")
        return False
    with open(definition_path, 'r') as f:
        definition = yaml.safe_load(f)
    print(f"   ✓ Loaded successfully")
    print(f"   Keys: {list(definition.keys())}")
    print(f"   Apps: {len(definition.get('apps', {}))}")
    print(f"   Test suites: {len(definition.get('test_suites', {}))}")
    print(f"   Test combinations: {len(definition.get('test_run_combinations', {}))}")
    
    # Test resources config
    resources_path = Path(__file__).parent.parent / "hailo_apps" / "config" / "resources_config.yaml"
    print(f"\n3. Loading resources_config.yaml from: {resources_path}")
    if not resources_path.exists():
        print(f"   ❌ File not found!")
        return False
    with open(resources_path, 'r') as f:
        resources = yaml.safe_load(f)
    print(f"   ✓ Loaded successfully")
    print(f"   Keys: {list(resources.keys())[:10]}...")  # Show first 10 keys
    
    # Verify test combinations
    print(f"\n4. Verifying test combinations:")
    test_combinations = control.get("test_combinations", {})
    definition_combinations = definition.get("test_run_combinations", {})
    print(f"   Control config combinations: {list(test_combinations.keys())}")
    print(f"   Definition config combinations: {list(definition_combinations.keys())}")
    
    # Check if all control combinations exist in definition
    missing = []
    for combo_name in test_combinations.keys():
        if combo_name not in definition_combinations:
            missing.append(combo_name)
    if missing:
        print(f"   ⚠️  Warning: Control combinations not found in definition: {missing}")
    else:
        print(f"   ✓ All control combinations found in definition")
    
    # Verify apps
    print(f"\n5. Verifying apps:")
    control_custom = control.get("custom_tests", {}).get("apps", {})
    definition_apps = definition.get("apps", {})
    print(f"   Custom tests apps: {list(control_custom.keys())}")
    print(f"   Definition apps: {list(definition_apps.keys())}")
    
    missing_apps = []
    for app_name in control_custom.keys():
        if app_name not in definition_apps:
            missing_apps.append(app_name)
    if missing_apps:
        print(f"   ⚠️  Warning: Custom test apps not found in definition: {missing_apps}")
    else:
        print(f"   ✓ All custom test apps found in definition")
    
    # Verify test suites referenced by apps
    print(f"\n6. Verifying test suite references:")
    all_suites = set(definition.get("test_suites", {}).keys())
    referenced_suites = set()
    for app_name, app_config in definition_apps.items():
        default_suites = app_config.get("default_test_suites", [])
        extra_suites = app_config.get("extra_test_suites", [])
        referenced_suites.update(default_suites)
        referenced_suites.update(extra_suites)
    
    missing_suites = referenced_suites - all_suites
    if missing_suites:
        print(f"   ❌ Error: Referenced test suites not found: {missing_suites}")
        return False
    else:
        print(f"   ✓ All referenced test suites exist")
        print(f"   Total referenced suites: {len(referenced_suites)}")
    
    print("\n" + "=" * 80)
    print("✅ ALL CONFIGURATION FILES VERIFIED SUCCESSFULLY")
    print("=" * 80)
    return True

if __name__ == "__main__":
    success = verify_configs()
    exit(0 if success else 1)

