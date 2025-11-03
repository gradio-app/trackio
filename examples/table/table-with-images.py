#!/usr/bin/env python3
"""
Example: Logging Tables with Images

This example demonstrates the new capability to include trackio.Image objects 
in trackio.Table columns. The images will be displayed as thumbnails in the 
dashboard with captions as alt text.

Run with: python examples/table/table-with-images.py
"""

import numpy as np
import pandas as pd
from PIL import Image as PILImage

import trackio

def create_sample_images():
    """Create some sample images for demonstration."""
    images = []
    
    # Create a red square
    red_square = np.full((100, 100, 3), [255, 0, 0], dtype=np.uint8)
    images.append(trackio.Image(red_square, caption="Red Square"))
    
    # Create a blue circle
    blue_data = np.zeros((100, 100, 3), dtype=np.uint8)
    center = 50
    radius = 40
    y, x = np.ogrid[:100, :100]
    mask = (x - center) ** 2 + (y - center) ** 2 <= radius ** 2
    blue_data[mask] = [0, 0, 255]
    images.append(trackio.Image(blue_data, caption="Blue Circle"))
    
    # Create a gradient
    gradient = np.zeros((100, 100, 3), dtype=np.uint8)
    for i in range(100):
        gradient[i, :, 1] = int(255 * i / 100)  # Green gradient
    images.append(trackio.Image(gradient, caption="Green Gradient"))
    
    # Create a checkerboard pattern
    checkerboard = np.zeros((100, 100, 3), dtype=np.uint8)
    for i in range(0, 100, 20):
        for j in range(0, 100, 20):
            if (i // 20 + j // 20) % 2 == 0:
                checkerboard[i:i+20, j:j+20] = [255, 255, 255]
    images.append(trackio.Image(checkerboard, caption="Checkerboard"))
    
    return images

def main():
    # Initialize trackio
    run = trackio.init(project="table-with-images-demo", name="sample-run")
    
    print("🎨 Creating sample images...")
    images = create_sample_images()
    
    print("📊 Creating table with images...")
    
    # Create a table with different types of data including images
    data = {
        "experiment_id": [1, 2, 3, 4],
        "model_type": ["CNN", "ResNet", "VGG", "Custom"],
        "accuracy": [0.85, 0.92, 0.88, 0.95],
        "loss": [0.15, 0.08, 0.12, 0.05],
        "sample_output": images,  # This is the new feature!
        "notes": [
            "Basic convolutional model", 
            "Deep residual network", 
            "Very deep network",
            "Custom architecture"
        ]
    }
    
    df = pd.DataFrame(data)
    table = trackio.Table(dataframe=df)
    
    # Log the table
    trackio.log({"experiment_results": table})
    
    print("✅ Table with images logged successfully!")
    
    # Also log some individual images for comparison
    print("🖼️  Logging individual images...")
    for i, img in enumerate(images):
        trackio.log({f"individual_image_{i+1}": img})
    
    # Log some metrics over time to make the dashboard more interesting
    print("📈 Logging some metrics...")
    for step in range(10):
        trackio.log({
            "training_loss": 1.0 * np.exp(-step * 0.1) + 0.1,
            "validation_accuracy": 0.5 + 0.4 * (1 - np.exp(-step * 0.15)),
            "learning_rate": 0.001 * (0.95 ** step)
        }, step=step)
    
    # Create another table with mixed content (some rows with images, some without)
    print("📋 Creating mixed content table...")
    mixed_data = {
        "test_id": [1, 2, 3, 4, 5],
        "test_type": ["visual", "numerical", "visual", "numerical", "visual"],
        "result_image": [images[0], None, images[1], None, images[2]],
        "score": [95.5, 87.2, 91.8, 89.1, 93.4],
        "passed": [True, True, True, False, True]
    }
    
    mixed_df = pd.DataFrame(mixed_data)
    mixed_table = trackio.Table(dataframe=mixed_df)
    trackio.log({"mixed_test_results": mixed_table})
    
    print("✅ Mixed content table logged!")
    
    # Finish the run
    trackio.finish()
    
    print("\n" + "="*60)
    print("🎉 Example completed successfully!")
    print("="*60)
    print("📊 What was logged:")
    print("  • experiment_results: Table with images in 'sample_output' column")
    print("  • mixed_test_results: Table with some rows having images, some not")
    print("  • individual_image_1-4: Individual images for comparison")
    print("  • training_loss, validation_accuracy, learning_rate: Time series metrics")
    print("\n🌐 View the results in your trackio dashboard!")
    print("💡 In the tables, images will display as thumbnails with captions.")
    print("   The captions appear as alt text when you hover over the images.")

if __name__ == "__main__":
    main()