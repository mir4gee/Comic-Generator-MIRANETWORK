import torch
from diffusers import DiffusionPipeline

# Load the FLUX pipeline
pipe = DiffusionPipeline.from_pretrained(
    "black-forest-labs/FLUX.1-dev",
    use_auth_token=True,  # Use the Hugging Face token for gated repo access
    torch_dtype=torch.bfloat16  # Efficient model loading with bfloat16
)

# Enable model offloading to save VRAM (optional)
pipe.enable_model_cpu_offload()

# Use GPU if available, otherwise fallback to CPU
device = "cuda" if torch.cuda.is_available() else "cpu"
pipe.to(device)

# Define the prompt and generation parameters
prompt = "A cat holding a sign that says hello world"
generation_params = {
    "height": 1024,
    "width": 1024,
    "guidance_scale": 3.5,
    "num_inference_steps": 50,
    "max_sequence_length": 512,
    "generator": torch.manual_seed(0)  # Set a deterministic seed for reproducibility
}

# Generate the image
print("Generating image...")
image = pipe(prompt, **generation_params).images[0]

# Save the image to a file
output_path = "flux-dev.png"
image.save(output_path)
print(f"Image saved at: {output_path}")