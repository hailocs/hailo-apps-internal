# Download files
Invoke-WebRequest "https://hailo-csdata.s3.eu-west-2.amazonaws.com/resources/images/bus.jpg" -OutFile "bus.jpg"

Invoke-WebRequest "https://hailo-csdata.s3.eu-west-2.amazonaws.com/resources/hefs/h8/clip_text_encoder_vit_l_14_laion2B.hef" `
-OutFile "clip_text_encoder_vit_l_14_laion2B.hef"

Invoke-WebRequest "https://hailo-csdata.s3.eu-west-2.amazonaws.com/resources/hefs/h8/clip_vit_l_14_laion2B_image_encoder.hef" `
-OutFile "clip_vit_l_14_laion2B_image_encoder.hef"

Invoke-WebRequest "https://hailo-csdata.s3.eu-west-2.amazonaws.com/resources/external+bin+files/text_projection.bin" `
-OutFile "text_projection.bin"

# Enter tokenizer folder
cd tokenizer

# Download tokenizer files
Invoke-WebRequest "https://hailo-csdata.s3.eu-west-2.amazonaws.com/resources/npy+files/embedding_weights.npy" `
-OutFile "ViT-L-14_laion2b_s32b_b82k.npy"

Invoke-WebRequest "https://hailo-csdata.s3.eu-west-2.amazonaws.com/resources/txt+files/bpe_simple_vocab_16e6.txt" `
-OutFile "bpe_simple_vocab_16e6.txt"

# Return to previous folder
cd ..