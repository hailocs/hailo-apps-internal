$ErrorActionPreference = "Stop"

# mkdir resources
New-Item -ItemType Directory -Force -Path resources | Out-Null

# cd resources
Set-Location resources

$baseUrl = "https://hailo-csdata.s3.eu-west-2.amazonaws.com/resources/v2a_demo"
$files = @(
    "en_US-joe-medium.onnx",
    "en_US-joe-medium.onnx.json",
    "go_hailo.onnx",
    "hey_hailo.onnx",
    "tool_embeddings_cache.npz",
    "word_embeddings_weight.npy"
)

foreach ($file in $files) {
    Write-Host "Downloading $file..."
    Invoke-WebRequest -Uri "$baseUrl/$file" -OutFile $file
}

# cd ..
Set-Location ..