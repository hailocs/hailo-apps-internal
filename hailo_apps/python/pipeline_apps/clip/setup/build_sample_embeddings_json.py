import json
import sys
from pathlib import Path
from hailo_apps.python.core.common.core import resolve_hef_paths
from hailo_apps.python.core.common.defines import CLIP_PIPELINE
from hailo_apps.python.core.common.installation_utils import detect_hailo_arch
sys.path.insert(0, str(Path(__file__).parent.parent))  # Add parent directory to path to import clip_text_utils
from clip_text_utils import run_text_encoder_inference, DEFAULT_TEXT_PROJECTION_PATH

def create_embeddings_json(text_entries, hef_path, timeout_ms, output_filename):
    """Create an embeddings JSON file from a list of text entries."""
    # Configuration for the embeddings JSON
    config = {
        "threshold": 0.5,
        "text_prefix": "A photo of a ",
        "ensemble_template": [
            "a photo of a {}.",
            "a photo of the {}.",
            "a photo of my {}.",
            "a photo of a big {}.",
            "a photo of a small {}."
        ],
        "entries": []
    }
    
    # Process each text entry
    print(f"\nProcessing {len(text_entries)} text entries for {output_filename}...")
    for text in text_entries:
        print(f"Processing: {text}")
        
        # Add text prefix to match CLIP behavior
        full_text = config["text_prefix"] + text

        # Run inference to get normalized embeddings
        embedding = run_text_encoder_inference(
            text=full_text,
            hef_path=hef_path,
            text_projection_path=DEFAULT_TEXT_PROJECTION_PATH,
            timeout_ms=timeout_ms
        )
        
        # Convert to list (embedding shape is (1, embedding_dim) for single text)
        embedding_list = embedding[0].tolist()
        
        # Add entry to config
        config["entries"].append({
            "text": text,
            "embedding": embedding_list,
            "negative": False,
            "ensemble": False
        })
    
    # Save to JSON file
    output_path = Path(__file__).parent / output_filename
    with open(output_path, 'w') as f:
        json.dump(config, f, indent=None)  # Compact format like the example
    
    print(f"✓ Embeddings saved to: {output_path}")
    print(f"  Total entries: {len(config['entries'])}")
    print(f"  Embedding dimension: {len(config['entries'][0]['embedding'])}")
    
    return output_path

if __name__ == '__main__':
    # Configuration
    models = resolve_hef_paths(hef_paths=None, app_name=CLIP_PIPELINE, arch=detect_hailo_arch())
    hef_path = models[2].path
    timeout_ms = 1000
    
    # Text entries for embeddings.json (your main embeddings)
    main_text_entries = ['desk', 'keyboard', 'spinner', 'Raspberry Pi', 'Unicorn mouse pad', 'Xenomorph']
    
    # Create embeddings.json
    create_embeddings_json(main_text_entries, hef_path, timeout_ms, '../example_embeddings.json')
    
    print("\n✓ All embedding files created successfully!")