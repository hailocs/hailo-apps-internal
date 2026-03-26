#!/usr/bin/env python3
"""Extract ONNX postprocessing subgraph."""

import onnx
from onnx import helper, numpy_helper
import numpy as np
import json
import argparse
import os
from pathlib import Path


def extract_postprocess_subgraph(input_model_path, output_model_path, cutoff_node_names, skip_sigmoid=False):
    """
    Extract the post-processing portion of an ONNX model by cutting off at specified nodes.
    The outputs of the cutoff nodes become the inputs to the new post-processing model.
    
    Args:
        input_model_path (str): Path to the original ONNX model
        output_model_path (str): Path to save the modified model (post-processing only)
        cutoff_node_names (list): List of node names to cut at (these nodes are EXCLUDED,
                                  their outputs become the new inputs)
        skip_sigmoid (bool): If True, skip (remove) Sigmoid nodes that immediately follow
                           the cutoff nodes. Useful when HEF compilation adds sigmoid
                           activation but ONNX postprocessing expects pre-activation values.
    
    Returns:
        None (saves modified model to output_model_path)
    """
    # Load the original model
    model = onnx.load(input_model_path)
    graph = model.graph
    
    # Find the cutoff nodes and get their output tensor names
    cutoff_nodes = {}  # node_name -> node
    intermediate_input_names = []
    
    for node in graph.node:
        if node.name in cutoff_node_names:
            cutoff_nodes[node.name] = node
            # Add all outputs of this node as new inputs
            intermediate_input_names.extend(node.output)
    
    if len(cutoff_nodes) != len(cutoff_node_names):
        found_names = set(cutoff_nodes.keys())
        missing = set(cutoff_node_names) - found_names
        print(f"Warning: Could not find nodes: {missing}")
    
    print(f"Cutoff nodes (EXCLUDED): {list(cutoff_nodes.keys())}")
    print(f"New input tensors (outputs of cutoff nodes): {intermediate_input_names}")
    
    # If skip_sigmoid is enabled, find and mark Sigmoid nodes reachable from cutoff outputs
    # by traversing through Reshape and Concat nodes
    sigmoid_nodes_to_skip = set()
    sigmoid_output_mapping = {}  # sigmoid_output -> original_input (bypass mapping)
    
    if skip_sigmoid:
        # Build a forward graph: tensor_name -> list of nodes that consume it
        tensor_consumers = {}
        for node in graph.node:
            for inp in node.input:
                if inp not in tensor_consumers:
                    tensor_consumers[inp] = []
                tensor_consumers[inp].append(node)
        
        # Traverse forward from cutoff outputs through Reshape/Concat to find Sigmoids
        tensors_to_explore = list(intermediate_input_names)
        explored_tensors = set()
        
        print("Traversing forward from cutoff outputs to find Sigmoid nodes...")
        while tensors_to_explore:
            current_tensor = tensors_to_explore.pop(0)
            if current_tensor in explored_tensors:
                continue
            explored_tensors.add(current_tensor)
            
            # Find nodes consuming this tensor
            consuming_nodes = tensor_consumers.get(current_tensor, [])
            
            for node in consuming_nodes:
                if node.op_type == "Sigmoid":
                    # Found a Sigmoid - mark it for skipping
                    sigmoid_nodes_to_skip.add(node.name)
                    # Map: sigmoid output -> sigmoid input (to bypass the sigmoid)
                    if len(node.input) == 1 and len(node.output) == 1:
                        sigmoid_output_mapping[node.output[0]] = node.input[0]
                        print(f"  Found Sigmoid to skip: '{node.name}' ({node.input[0]} -> {node.output[0]})")
                
                elif node.op_type in ["Reshape", "Concat"]:
                    # Continue traversing through Reshape/Concat nodes
                    print(f"  Traversing through {node.op_type}: '{node.name}'")
                    for output in node.output:
                        if output not in explored_tensors:
                            tensors_to_explore.append(output)
    
    print(f"Sigmoid nodes to skip: {len(sigmoid_nodes_to_skip)}")
    
    # Build a map of node names for fast lookup
    node_name_set = set(cutoff_node_names) | sigmoid_nodes_to_skip
    
    # Keep only nodes that are NOT in the cutoff list and come after the cutoff
    # Strategy: Keep nodes whose inputs depend on the intermediate tensors
    nodes_to_keep_by_name = set()  # Use node names (strings) not NodeProto objects
    tensors_available = set(intermediate_input_names)
    
    # Also include all initializers as available tensors
    for init in graph.initializer:
        tensors_available.add(init.name)
    
    # If skipping sigmoids, treat sigmoid outputs as available by mapping to their inputs
    # This allows downstream nodes to be discovered
    if skip_sigmoid and sigmoid_output_mapping:
        print("Making sigmoid input tensors available as their outputs for graph traversal...")
        for sigmoid_out, sigmoid_in in sigmoid_output_mapping.items():
            if sigmoid_in in tensors_available:
                tensors_available.add(sigmoid_out)
                print(f"  Mapping {sigmoid_out} -> {sigmoid_in} (available)")
    
    # Iteratively find all nodes whose inputs are satisfied
    changed = True
    iterations = 0
    max_iterations = len(graph.node) + 10
    
    while changed and iterations < max_iterations:
        changed = False
        iterations += 1
        
        for node in graph.node:
            # Skip if already processed or in cutoff list
            if node.name in nodes_to_keep_by_name or node.name in node_name_set:
                continue
            
            # Check if all inputs to this node are available
            if all(inp in tensors_available for inp in node.input):
                nodes_to_keep_by_name.add(node.name)
                # Make outputs available for downstream nodes
                for out in node.output:
                    if out not in tensors_available:
                        tensors_available.add(out)
                        # If this output is a sigmoid input being bypassed, also make sigmoid output available
                        if skip_sigmoid and out in sigmoid_output_mapping.values():
                            for sigmoid_out, sigmoid_in in sigmoid_output_mapping.items():
                                if sigmoid_in == out:
                                    tensors_available.add(sigmoid_out)
                                    print(f"  Auto-mapping sigmoid: {sigmoid_out} -> {sigmoid_in} (now available)")
                        changed = True
    
    print(f"Kept {len(nodes_to_keep_by_name)} nodes out of {len(graph.node)} original nodes")
    
    # Filter nodes: keep only those in nodes_to_keep
    new_nodes = [node for node in graph.node if node.name in nodes_to_keep_by_name]
    
    # If we're skipping sigmoids, rewire nodes that consume sigmoid outputs
    if skip_sigmoid and sigmoid_output_mapping:
        print(f"Rewiring {len(new_nodes)} nodes to bypass sigmoids...")
        rewired_count = 0
        for node in new_nodes:
            # Replace any sigmoid outputs in node inputs with original sigmoid inputs
            new_inputs = []
            for inp in node.input:
                if inp in sigmoid_output_mapping:
                    new_inputs.append(sigmoid_output_mapping[inp])
                    rewired_count += 1
                    print(f"    Rewired node '{node.name}' input: {inp} -> {sigmoid_output_mapping[inp]}")
                else:
                    new_inputs.append(inp)
            # Update node inputs
            del node.input[:]
            node.input.extend(new_inputs)
        print(f"Rewired {rewired_count} input connections to bypass sigmoids")
    
    # Remove incompatible attributes and fix nodes for opset 11 compatibility
    # Operators that changed from input-based to attribute-based between opsets
    OPSET11_INPUT_TO_ATTR = {
        "Split": ("split", 1),       # (attribute_name, input_index)
        "ReduceMax": ("axes", 1),
        "ReduceMin": ("axes", 1),
        "Unsqueeze": ("axes", 1),
        "Squeeze": ("axes", 1),
    }
    
    for node in new_nodes:
        if node.op_type == "Reshape":
            # Remove 'allowzero' attribute if present (not in opset 11)
            attrs_to_remove = []
            for i, attr in enumerate(node.attribute):
                if attr.name == "allowzero":
                    attrs_to_remove.append(i)
            # Remove in reverse order to maintain indices
            for i in reversed(attrs_to_remove):
                del node.attribute[i]
        
        elif node.op_type in OPSET11_INPUT_TO_ATTR:
            # Convert input-based parameters to attributes for opset 11 compatibility
            attr_name, input_idx = OPSET11_INPUT_TO_ATTR[node.op_type]
            if len(node.input) > input_idx:
                param_input_name = node.input[input_idx]
                # Find the initializer with parameter values
                param_values = None
                for init in graph.initializer:
                    if init.name == param_input_name:
                        param_values = numpy_helper.to_array(init)
                        break
                
                if param_values is not None:
                    # Remove the parameter input
                    del node.input[input_idx]
                    # Add parameter as an attribute
                    param_attr = helper.make_attribute(attr_name, param_values.tolist())
                    node.attribute.append(param_attr)
    
    # Create new input value infos for the intermediate tensors
    new_inputs = []
    for input_name in intermediate_input_names:
        # Try to find shape/type info from value_info
        found = False
        
        # Check in value_info (intermediate tensors)
        for value_info in graph.value_info:
            if value_info.name == input_name:
                new_inputs.append(value_info)
                found = True
                break
        
        # Check in existing outputs
        if not found:
            for output in graph.output:
                if output.name == input_name:
                    new_inputs.append(output)
                    found = True
                    break
        
        # Check in existing inputs
        if not found:
            for inp in graph.input:
                if inp.name == input_name:
                    new_inputs.append(inp)
                    found = True
                    break
        
        if not found:
            print(f"Warning: Could not infer type/shape for {input_name}, creating placeholder")
            # Create a placeholder - you may need to manually specify the shape
            new_inputs.append(
                helper.make_tensor_value_info(input_name, onnx.TensorProto.FLOAT, None)
            )
    
    # Filter initializers: keep only those used by remaining nodes
    used_initializers = set()
    for node in new_nodes:
        for inp in node.input:
            used_initializers.add(inp)
    
    new_initializers = [init for init in graph.initializer 
                       if init.name in used_initializers and init.name not in intermediate_input_names]
    
    # Create new graph
    new_graph = helper.make_graph(
        new_nodes,
        graph.name + "_postprocess",
        new_inputs,
        graph.output,  # Keep original outputs
        new_initializers
    )
    
    # If we skipped sigmoids, update graph outputs that reference sigmoid outputs
    if skip_sigmoid and sigmoid_output_mapping:
        print("Updating graph outputs to bypass skipped sigmoids...")
        new_outputs = []
        for output in new_graph.output:
            if output.name in sigmoid_output_mapping:
                # This output was a sigmoid output - replace with sigmoid input
                original_tensor = sigmoid_output_mapping[output.name]
                print(f"  Replacing output '{output.name}' with '{original_tensor}'")
                # Create new output with the bypassed tensor name
                new_output = helper.make_tensor_value_info(
                    original_tensor,
                    output.type.tensor_type.elem_type,
                    [dim.dim_value if dim.HasField('dim_value') else None 
                     for dim in output.type.tensor_type.shape.dim] if output.type.HasField('tensor_type') else None
                )
                new_outputs.append(new_output)
            else:
                new_outputs.append(output)
        
        # Replace outputs
        del new_graph.output[:]
        new_graph.output.extend(new_outputs)
    
    # Create new model with opset 11 for compatibility
    new_model = helper.make_model(new_graph, producer_name="onnx-postprocess-extractor")
    
    # Set opset version to 11 (max supported by older ONNXRuntime versions)
    # Clear existing opset imports and set to version 11
    del new_model.opset_import[:]
    opset = new_model.opset_import.add()
    opset.domain = ""
    opset.version = 11
    
    # Set IR version to 7 (compatible with opset 11)
    new_model.ir_version = 7
    
    # Check and save
    try:
        onnx.checker.check_model(new_model)
        print("Model check passed!")
    except Exception as e:
        print(f"Model check warning: {e}")
    
    onnx.save(new_model, output_model_path)
    
    print(f"\nPost-processing model saved to {output_model_path}")
    print(f"New inputs: {intermediate_input_names}")
    print(f"Original outputs preserved")


def extract_hef_like_intermediate_model(input_model_path, output_model_path, intermediate_output_names):
    """
    Extract HEF-like intermediate model: from input to cutoff nodes.
    This creates a model that outputs the same tensors as HEF outputs,
    so applying postprocessing ONNX on top is equivalent to full ONNX.
    
    Args:
        input_model_path (str): Path to the original full ONNX model
        output_model_path (str): Path to save the intermediate model
        intermediate_output_names (list): List of tensor names to use as outputs
                                         (outputs of the cutoff nodes)
    
    Returns:
        None (saves modified model to output_model_path)
    """
    # Load the full model
    model = onnx.load(input_model_path)
    
    print(f"\nExtracting HEF-like intermediate model...")
    print(f"Intermediate outputs to extract ({len(intermediate_output_names)}):")
    for name in intermediate_output_names:
        print(f"  {name}")
    
    # Verify that all requested tensors exist in the graph
    available_tensors = set()
    for node in model.graph.node:
        available_tensors.update(node.output)
    
    missing_tensors = set(intermediate_output_names) - available_tensors
    if missing_tensors:
        print(f"Warning: The following tensors were not found in the model:")
        for t in missing_tensors:
            print(f"  {t}")
    
    # Create new outputs from the intermediate tensors
    new_outputs = []
    for tensor_name in intermediate_output_names:
        # Create output with unknown shape (will be inferred at runtime)
        new_output = helper.make_tensor_value_info(
            tensor_name,
            onnx.TensorProto.FLOAT,
            None  # Shape will be inferred
        )
        new_outputs.append(new_output)
    
    # Replace the model outputs with intermediate outputs
    model.graph.ClearField('output')
    model.graph.output.extend(new_outputs)
    
    # Check and save
    try:
        onnx.checker.check_model(model)
        print("Model check passed!")
    except Exception as e:
        print(f"Model check warning: {e}")
    
    onnx.save(model, output_model_path)
    
    print(f"\nHEF-like intermediate model saved to {output_model_path}")
    print(f"Outputs ({len(new_outputs)}):")
    for o in model.graph.output:
        print(f"  {o.name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Extract ONNX postprocessing subgraph from config')
    parser.add_argument('--config', type=str, required=True,
                       help='Path to config_onnx_<net>.json file')
    parser.add_argument('--skip-sigmoid', action='store_true',
                       help='Skip sigmoid nodes after cutoff (for HEF with sigmoid outputs)')
    args = parser.parse_args()
    
    # Load JSON config
    with open(args.config, 'r') as f:
        config = json.load(f)
    
    # Extract paths from config
    full_onnx_path = config.get('full_onnx_path')
    if not full_onnx_path:
        raise ValueError("Config must contain 'full_onnx_path'")
    
    # Get the base directory of the config file
    config_dir = Path(args.config).parent
    
    # Resolve full ONNX path relative to config directory if it's relative
    if not Path(full_onnx_path).is_absolute():
        full_onnx_path = str(config_dir / full_onnx_path)
    
    # Extract cutoff node names from output_tensor_mapping
    # The ONNX tensor names (first element of each mapping) contain the node names
    # We need to strip the "_output_0" suffix and "/Conv" to get the node name
    output_tensor_mapping = config.get('output_tensor_mapping', {})
    if not output_tensor_mapping:
        raise ValueError("Config must contain 'output_tensor_mapping'")
    
    # Extract unique cutoff node names
    cutoff_node_names = []
    for hef_name, (onnx_tensor_name, shape) in output_tensor_mapping.items():
        # Convert tensor name like "/model.23/one2one_cv2.0/one2one_cv2.0.2/Conv_output_0"
        # to node name "/model.23/one2one_cv2.0/one2one_cv2.0.2/Conv"
        if onnx_tensor_name.endswith('_output_0'):
            node_name = onnx_tensor_name.rsplit('_output_0', 1)[0]
        elif onnx_tensor_name.endswith('/Conv'):
            node_name = onnx_tensor_name
        else:
            # Assume the last component before output suffix is the node
            node_name = onnx_tensor_name.rsplit('/', 1)[0]
        
        if node_name not in cutoff_node_names:
            cutoff_node_names.append(node_name)
    
    # Construct output postprocessing ONNX filename
    postproc_onnx_path = config.get('postproc_onnx_path', 'postprocessing.onnx')
    
    # Resolve output path relative to config directory if it's relative
    if not Path(postproc_onnx_path).is_absolute():
        output_model_path = str(config_dir / postproc_onnx_path)
    else:
        output_model_path = postproc_onnx_path
    
    # Print configuration
    print("="*80)
    print("ONNX Postprocessing Extraction Configuration")
    print("="*80)
    print(f"Config file: {args.config}")
    print(f"Full ONNX model: {full_onnx_path}")
    print(f"Output postprocessing ONNX: {output_model_path}")
    print(f"Skip sigmoid: {args.skip_sigmoid}")
    print(f"Cutoff nodes ({len(cutoff_node_names)}): {cutoff_node_names}")
    print("="*80)
    
    # Extract postprocessing subgraph
    extract_postprocess_subgraph(
        full_onnx_path,
        output_model_path,
        cutoff_node_names,
        skip_sigmoid=args.skip_sigmoid
    )
    
    # Also extract HEF-like intermediate model (input to cutoff nodes)
    hef_like_path = config.get('hef_like_proc_onnx_path')
    if hef_like_path:
        # Resolve path relative to config directory
        if not Path(hef_like_path).is_absolute():
            hef_like_output_path = str(config_dir / hef_like_path)
        else:
            hef_like_output_path = hef_like_path
        
        # Get the intermediate output tensor names (outputs of cutoff nodes)
        intermediate_output_names = [onnx_tensor_name for hef_name, (onnx_tensor_name, shape) 
                                    in output_tensor_mapping.items()]
        
        print("\n" + "="*80)
        print("HEF-like Intermediate Model Extraction")
        print("="*80)
        print(f"Output HEF-like intermediate ONNX: {hef_like_output_path}")
        print("="*80)
        
        extract_hef_like_intermediate_model(
            full_onnx_path,
            hef_like_output_path,
            intermediate_output_names
        )
    else:
        print("\nSkipping HEF-like intermediate model extraction (hef_like_proc_onnx_path not in config)")
