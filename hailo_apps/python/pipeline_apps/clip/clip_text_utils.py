"""
CLIP Text Utilities
Handles tokenization and token embedding for CLIP text encoder.
Provides tokenizer and pre-computed token embedding LUT (Look-Up Table).
"""
import os
from pathlib import Path
from tokenizers import Tokenizer
import numpy as np
from hailo_platform import VDevice, FormatType, HailoSchedulingAlgorithm
from hailo_apps.python.core.common.core import get_resource_path
from hailo_apps.python.core.common.installation_utils import detect_hailo_arch
from hailo_apps.python.core.common.defines import HAILO_ARCH_KEY, HAILO8_ARCH, HAILO8L_ARCH, RESOURCES_JSON_DIR_NAME, RESOURCES_NPY_DIR_NAME

# Default paths (in setup subfolder)
DEFAULT_TOKENIZER_PATH = get_resource_path(pipeline_name=None, resource_type=RESOURCES_JSON_DIR_NAME, arch=None, model="clip_tokenizer.json")
DEFAULT_TOKEN_EMBEDDING_PATH = get_resource_path(pipeline_name=None, resource_type=RESOURCES_NPY_DIR_NAME, arch=None, model="token_embedding_lut.npy")
DEFAULT_TEXT_PROJECTION_PATH = get_resource_path(pipeline_name=None, resource_type=RESOURCES_NPY_DIR_NAME, arch=None, model="text_projection.npy")

# Hailo HEF layer names for CLIP ViT-B/32 text encoder
# Use `hailortcli parse-hef <hef_path>` to inspect layer names for other models
DEFAULT_INPUT_LAYER_NAME = 'clip_vit_b_32_text_encoder/input_layer1'  # UINT16, NHWC(1x77x512)
DEFAULT_OUTPUT_LAYER_NAME = 'clip_vit_b_32_text_encoder/normalization25'  # UINT8, NHWC(1x77x512)


def load_clip_tokenizer(tokenizer_path=None):
    """Load CLIP tokenizer from local file."""
    if tokenizer_path is None:
        tokenizer_path = DEFAULT_TOKENIZER_PATH

    tokenizer_file = Path(tokenizer_path)

    # Check if tokenizer exists locally
    if not tokenizer_file.exists():
        raise FileNotFoundError(f"Tokenizer file not found: {tokenizer_file}")

    return Tokenizer.from_file(str(tokenizer_file))


def tokenize_text(text, tokenizer=None, max_length=77, tokenizer_path=None):
    """Tokenize text using CLIP tokenizer and return numpy int32 input_ids."""
    if tokenizer is None:
        tokenizer = load_clip_tokenizer(tokenizer_path)

    # Handle single string or list of strings
    if isinstance(text, str):
        texts = [text]
    else:
        texts = list(text)

    # Tokenize all texts
    all_tokens = []
    for single_text in texts:
        encoding = tokenizer.encode(single_text)
        ids = encoding.ids[:max_length]
        if len(ids) < max_length:
            ids = ids + [0] * (max_length - len(ids))
        all_tokens.append(ids)

    # Convert to numpy array
    input_ids = np.array(all_tokens, dtype=np.int32)

    return {"input_ids": input_ids}


def load_token_embeddings(embeddings_path=None):
    """Load pre-computed token embedding matrix (LUT)."""
    if embeddings_path is None:
        embeddings_path = DEFAULT_TOKEN_EMBEDDING_PATH

    embeddings_file = Path(embeddings_path)

    if not embeddings_file.exists():
        raise FileNotFoundError(f"Token embeddings file not found: {embeddings_file}")

    embeddings = np.load(embeddings_file)
    return embeddings


def tokens_to_embeddings(token_ids, token_embeddings=None, embeddings_path=None):
    """Convert token IDs to embedding vectors using token embedding LUT."""
    if token_embeddings is None:
        token_embeddings = load_token_embeddings(embeddings_path)

    # Look up embeddings for each token ID
    embeddings = token_embeddings[token_ids]

    return embeddings.astype(np.float32)


def prepare_text_for_encoder(text, tokenizer=None, token_embeddings=None, max_length=77,
                             tokenizer_path=None, embeddings_path=None):
    """Complete pipeline: text → token IDs → token embeddings."""
    # Load tokenizer if not provided
    if tokenizer is None:
        tokenizer = load_clip_tokenizer(tokenizer_path)

    # Load token embeddings if not provided
    if token_embeddings is None:
        token_embeddings = load_token_embeddings(embeddings_path)

    # Step 1: Tokenize text to get token IDs
    tokens = tokenize_text(text, tokenizer, max_length, tokenizer_path)
    token_ids = tokens['input_ids']

    # Step 2: Convert token IDs to embeddings
    embeddings = tokens_to_embeddings(token_ids, token_embeddings, embeddings_path)

    return {
        'token_ids': token_ids,
        'token_embeddings': embeddings
    }


def preprocess_for_text_encoder(token_embeddings, token_ids, sequence_length=77,
                                end_of_text_token_id=49407, pad_token_id=0):
    """Preprocess token embeddings for CLIP text encoder (Hailo model input)."""
    batch_size = token_embeddings.shape[0]
    current_length = token_embeddings.shape[1]
    embedding_dim = token_embeddings.shape[2]

    # Calculate padding length
    padding_length = sequence_length - current_length

    if padding_length > 0:
        # Pad with EOT token embedding or zeros
        # Find EOT token positions
        eot_mask = (token_ids == end_of_text_token_id)
        # Use first EOT position per batch or last token if none
        last_token_positions = []
        for b in range(batch_size):
            eot_indices = np.where(eot_mask[b])[0]
            if len(eot_indices) > 0:
                last_pos = int(eot_indices[0])
            else:
                last_pos = current_length - 1
            last_token_positions.append(last_pos)
        last_token_positions = np.array(last_token_positions, dtype=np.int32)

        # Use the embedding at last_token_position as pad embedding
        pad_embeddings = []
        for b in range(batch_size):
            pad_embeddings.append(
                np.repeat(
                    token_embeddings[b, last_token_positions[b]:last_token_positions[b] + 1, :],
                    padding_length,
                    axis=0,
                )
            )
        pad_embeddings = np.stack(pad_embeddings, axis=0)
        token_embeddings = np.concatenate([token_embeddings, pad_embeddings], axis=1)

    elif padding_length < 0:
        # Truncate to sequence_length
        token_embeddings = token_embeddings[:, :sequence_length, :]
        token_ids = token_ids[:, :sequence_length]

        # Recompute last_token_positions on truncated ids
        eot_mask = (token_ids == end_of_text_token_id)
        last_token_positions = []
        for b in range(batch_size):
            eot_indices = np.where(eot_mask[b])[0]
            if len(eot_indices) > 0:
                last_pos = int(eot_indices[0])
            else:
                last_pos = sequence_length - 1
            last_token_positions.append(last_pos)
        last_token_positions = np.array(last_token_positions, dtype=np.int32)

    else:
        # No padding/truncation needed
        eot_mask = (token_ids == end_of_text_token_id)
        last_token_positions = []
        for b in range(batch_size):
            eot_indices = np.where(eot_mask[b])[0]
            if len(eot_indices) > 0:
                last_pos = int(eot_indices[0])
            else:
                last_pos = current_length - 1
            last_token_positions.append(last_pos)
        last_token_positions = np.array(last_token_positions, dtype=np.int32)

    # Ensure the shape is correct
    assert token_embeddings.shape == (batch_size, sequence_length, embedding_dim), \
        f"Expected shape ({batch_size}, {sequence_length}, {embedding_dim}), got {token_embeddings.shape}"

    return {
        'token_embeddings': token_embeddings,
        'last_token_positions': last_token_positions,
    }


def prepare_text_for_hailo_encoder(text, tokenizer=None, token_embeddings=None,
                                   sequence_length=77, tokenizer_path=None,
                                   embeddings_path=None):
    """Prepare text all the way to Hailo CLIP text encoder input (float32 embeddings)."""
    encoded = prepare_text_for_encoder(
        text,
        tokenizer=tokenizer,
        token_embeddings=token_embeddings,
        max_length=sequence_length,
        tokenizer_path=tokenizer_path,
        embeddings_path=embeddings_path,
    )

    preprocessed = preprocess_for_text_encoder(
        encoded['token_embeddings'],
        encoded['token_ids'],
        sequence_length=sequence_length,
    )

    return {
        'token_embeddings': preprocessed['token_embeddings'],
        'last_token_positions': preprocessed['last_token_positions'],
    }


def text_encoding_postprocessing(encoder_output, last_token_positions, text_projection=None,
                                 text_projection_path=None):
    """Project encoder output to final text features using optional projection matrix."""
    if text_projection is None and text_projection_path is not None:
        proj_file = Path(text_projection_path)
        if not proj_file.exists():
            raise FileNotFoundError(f"Text projection file not found: {proj_file}")
        text_projection = np.load(proj_file)

    # Gather the features at last_token_positions (EOT token positions)
    # 
    # CLIP uses the EOT (End-Of-Text) token's hidden state as the text representation.
    # The encoder outputs a sequence of hidden states: shape (batch, sequence_length, hidden_dim)
    # e.g., (1, 77, 512) for ViT-B/32
    # 
    # We need to extract the hidden state at the EOT token position for each batch item.
    # For example:
    #   Text: "a photo of a cat"
    #   Tokens: [49406, 320, 1125, 539, 320, 2368, 49407, 0, 0, ...]
    #            ^start                        ^EOT   ^padding...
    #   EOT position: 6
    #   → Extract encoder_output[0, 6, :] as the text feature
    # 
    # This is different from BERT which uses the [CLS] token at position 0.
    # CLIP uses the last meaningful token (EOT) instead.
    batch_size = encoder_output.shape[0]
    embed_dim = encoder_output.shape[-1]
    gathered = np.zeros((batch_size, embed_dim), dtype=encoder_output.dtype)
    for b in range(batch_size):
        # Extract the hidden state at the EOT token position for this batch item
        gathered[b] = encoder_output[b, last_token_positions[b], :]

    if text_projection is not None:
        # Apply linear projection: (batch, dim) x (dim, out_dim)
        # 
        # IMPORTANT: Matrix orientation depends on the source library:
        # 
        # 1. HuggingFace transformers (CLIPModel.text_projection.weight):
        #    - Stored as (out_features, in_features) = (512, 512) or (768, 768)
        #    - This is PyTorch nn.Linear layer format
        #    - Usage: gathered @ text_projection.T (NEED transpose)
        # 
        # 2. OpenAI CLIP (model.text_projection):
        #    - Stored as (in_features, out_features) = (512, 512), (640, 640), etc.
        #    - This is a raw parameter (not nn.Linear)
        #    - Usage: gathered @ text_projection (NO transpose needed)
        # 
        # The weights are IDENTICAL, just stored in transposed orientations.
        # This code assumes HuggingFace format (hence the .T transpose).
        # If using OpenAI CLIP format (e.g., text_projection_RN50x4.npy), remove .T
        # gathered = gathered @ text_projection.T
        gathered = gathered @ text_projection

    # L2 normalization (normalize along the embedding dimension)
    norm = np.linalg.norm(gathered, axis=-1, keepdims=True)
    normalized = gathered / (norm + 1e-8)  # Add epsilon to avoid division by zero

    return normalized


def run_text_encoder_inference(text, hef_path, 
                               tokenizer=None, token_embeddings=None,
                               text_projection=None, tokenizer_path=None,
                               embeddings_path=None, text_projection_path=None,
                               input_layer_name=None, output_layer_name=None,
                               timeout_ms=1000):
    """
    Complete pipeline: text → Hailo text encoder → normalized text embeddings.
    
    This function handles the full CLIP text encoding pipeline:
    1. Tokenizes and prepares text for the encoder
    2. Runs inference on Hailo text encoder
    3. Post-processes the output with text projection and normalization
    
    Args:
        text (str or list[str]): 
            String or list of strings to encode.
            Examples: 
                - "a photo of a cat"
                - ["desk", "keyboard", "mouse"]
        
        hef_path (str or Path): 
            Path to CLIP text encoder HEF file.
            Example: "/path/to/clip_vit_b_32_text_encoder.hef"
        
        tokenizer (Tokenizer, optional): 
            Pre-loaded tokenizer instance. If None, loads from tokenizer_path or DEFAULT_TOKENIZER_PATH.
            Recommended: Load once and reuse for multiple calls.
            Default: None (auto-loads)
        
        token_embeddings (np.ndarray, optional): 
            Pre-loaded token embedding matrix (LUT), shape (vocab_size, embedding_dim).
            Example shapes:
                - ViT-B/32: (49408, 512)
                - RN50x4: (49408, 640)
            If None, loads from embeddings_path or DEFAULT_TOKEN_EMBEDDING_PATH.
            Recommended: Load once and reuse for multiple calls.
            Default: None (auto-loads)
        
        text_projection (np.ndarray, optional): 
            Pre-loaded text projection matrix, shape (embedding_dim, embedding_dim).
            Example shapes:
                - ViT-B/32: (512, 512)
                - RN50x4: (640, 640)
            If None, loads from text_projection_path or DEFAULT_TEXT_PROJECTION_PATH.
            **CRITICAL**: This must be provided (either directly or via path) for correct embeddings!
            Default: None (loads from text_projection_path if provided)
        
        tokenizer_path (str or Path, optional): 
            Path to tokenizer JSON file. Only used if tokenizer=None.
            Default: DEFAULT_TOKENIZER_PATH = "setup/clip_tokenizer.json"
        
        embeddings_path (str or Path, optional): 
            Path to token embeddings .npy file. Only used if token_embeddings=None.
            Default: DEFAULT_TOKEN_EMBEDDING_PATH = "setup/token_embedding_lut.npy"
        
        text_projection_path (str or Path, optional): 
            Path to text projection .npy file. Only used if text_projection=None.
            **IMPORTANT**: If both text_projection and text_projection_path are None,
            no projection is applied (resulting in incorrect embeddings)!
            Default: DEFAULT_TEXT_PROJECTION_PATH = "setup/text_projection.npy"
            Recommended: Always provide this for correct results!
        
        input_layer_name (str, optional): 
            HEF input layer name. Use `hailortcli parse-hef <hef_path>` to find layer names.
            Examples:
                - ViT-B/32: 'clip_vit_b_32_text_encoder/input_layer1'
                - RN50x4: 'clip_resnet_50x4_text_encoder/input_layer1'
            Default: DEFAULT_INPUT_LAYER_NAME (ViT-B/32 layer)
        
        output_layer_name (str, optional): 
            HEF output layer name. Use `hailortcli parse-hef <hef_path>` to find layer names.
            Examples:
                - ViT-B/32: 'clip_vit_b_32_text_encoder/normalization25'
                - RN50x4: 'clip_resnet_50x4_text_encoder/normalization25'
            Default: DEFAULT_OUTPUT_LAYER_NAME (ViT-B/32 layer)
        
        timeout_ms (int, optional): 
            Inference timeout in milliseconds.
            Default: 1000 (1 second)
    
    Returns:
        np.ndarray: 
            Normalized text embeddings, shape (batch_size, embedding_dim)
            - L2 normalized (unit vectors)
            - Ready for cosine similarity comparison with image embeddings
            Example shapes:
                - Single text: (1, 512) for ViT-B/32
                - Batch of 3 texts: (3, 512) for ViT-B/32
    
    Raises:
        FileNotFoundError: If tokenizer, embeddings, or projection files are not found
        RuntimeError: If HEF inference fails
    
    Example Usage:
        >>> # Basic usage (loads all files automatically)
        >>> embedding = run_text_encoder_inference(
        ...     text="a photo of a cat",
        ...     hef_path="clip_vit_b_32_text_encoder.hef",
        ...     text_projection_path="setup/text_projection.npy"  # IMPORTANT!
        ... )
        >>> print(embedding.shape)  # (1, 512)
        
        >>> # Efficient batch processing (load once, reuse)
        >>> tokenizer = load_clip_tokenizer()
        >>> token_embeddings = load_token_embeddings()
        >>> text_projection = np.load("setup/text_projection.npy")
        >>> 
        >>> texts = ["desk", "keyboard", "mouse"]
        >>> for text in texts:
        ...     embedding = run_text_encoder_inference(
        ...         text=text,
        ...         hef_path="clip_vit_b_32_text_encoder.hef",
        ...         tokenizer=tokenizer,
        ...         token_embeddings=token_embeddings,
        ...         text_projection=text_projection
        ...     )
        
        >>> # Custom model (e.g., RN50x4)
        >>> embedding = run_text_encoder_inference(
        ...     text="a photo of a dog",
        ...     hef_path="clip_resnet_50x4_text_encoder.hef",
        ...     embeddings_path="setup/token_embedding_lut_RN50x4.npy",
        ...     text_projection_path="setup/text_projection_RN50x4.npy",
        ...     input_layer_name='clip_resnet_50x4_text_encoder/input_layer1',
        ...     output_layer_name='clip_resnet_50x4_text_encoder/normalization25'
        ... )
        >>> print(embedding.shape)  # (1, 640)
    
    Notes:
        - **CRITICAL**: Always provide text_projection_path (or text_projection) for correct embeddings!
          Without it, embeddings will be completely wrong (cosine similarity ~0.02 instead of ~0.99).
        
        - For best performance with multiple texts, load tokenizer, token_embeddings, and 
          text_projection once and pass them to each call (avoids repeated file I/O).
        
        - The tokenizer is the same for all CLIP models (ViT, ResNet variants).
          Only token_embeddings and text_projection dimensions differ between models.
        
        - All CLIP models use vocabulary size 49408 but different embedding dimensions:
          * ViT-B/32, ViT-B/16: 512-dim
          * RN50x4: 640-dim  
          * ViT-L/14: 768-dim
    """
    # ========== SET DEFAULTS FOR ALL PATH ARGUMENTS ==========
    # Use default paths if not provided
    if tokenizer_path is None:
        tokenizer_path = DEFAULT_TOKENIZER_PATH
    
    if embeddings_path is None:
        embeddings_path = DEFAULT_TOKEN_EMBEDDING_PATH
    
    if text_projection_path is None:
        text_projection_path = DEFAULT_TEXT_PROJECTION_PATH
    
    if input_layer_name is None:
        input_layer_name = DEFAULT_INPUT_LAYER_NAME
    
    if output_layer_name is None:
        output_layer_name = DEFAULT_OUTPUT_LAYER_NAME
    
    # ========== LOAD RESOURCES IF NOT PROVIDED ==========
    # Load tokenizer if not provided
    if tokenizer is None:
        tokenizer = load_clip_tokenizer(tokenizer_path)
    
    # Load token embeddings if not provided
    if token_embeddings is None:
        token_embeddings = load_token_embeddings(embeddings_path)
    
    # Load text projection if not provided
    if text_projection is None:
        text_projection = np.load(text_projection_path)
    
    # ========== STEP 1: PREPARE TEXT INPUT ==========
    # Prepare text input (tokenization + embedding lookup + preprocessing)
    # Now passing the loaded tokenizer and token_embeddings directly
    prepared = prepare_text_for_hailo_encoder(
        text=text,
        tokenizer=tokenizer,
        token_embeddings=token_embeddings,
        tokenizer_path=None,  # Already loaded above
        embeddings_path=None  # Already loaded above
    )
    input_embeddings = prepared['token_embeddings']  # Shape: (batch, 77, 512) or (batch, 77, 640)
    last_token_positions = prepared['last_token_positions']  # Shape: (batch,)
    
    # ========== STEP 2: RUN HAILO INFERENCE ==========
    arch = detect_hailo_arch()
    params = VDevice.create_params()
    params.group_id = "SHARED"
    if arch in [HAILO8_ARCH, HAILO8L_ARCH]:
        params.multi_process_service = True
        params.scheduling_algorithm = HailoSchedulingAlgorithm.ROUND_ROBIN
    with VDevice(params) as vdevice:
        infer_model = vdevice.create_infer_model(str(hef_path))
        # Set format types before configuring the infer model
        infer_model.input(input_layer_name).set_format_type(FormatType.FLOAT32)
        infer_model.output(output_layer_name).set_format_type(FormatType.FLOAT32)
        with infer_model.configure() as configured_infer_model:
            bindings = configured_infer_model.create_bindings()
            input_buffer = np.empty(infer_model.input().shape, dtype=np.float32)
            input_buffer[:] = input_embeddings
            bindings.input().set_buffer(input_buffer)
            output_buffer = np.empty(infer_model.output().shape, dtype=np.float32)
            bindings.output().set_buffer(output_buffer)
            configured_infer_model.run([bindings], timeout_ms)
        output_buffer = bindings.output().get_buffer()

    # ========== STEP 3: POST-PROCESS ==========
    # Post-process the encoder output with text projection
    # Now passing the loaded text_projection directly
    normalized_embeddings = text_encoding_postprocessing(
        encoder_output=output_buffer,
        last_token_positions=last_token_positions,
        text_projection=text_projection,
        text_projection_path=None  # Already loaded above
    )
    
    return normalized_embeddings