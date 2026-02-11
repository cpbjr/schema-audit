"""Screenshot generation for Map Pack results.

Captures Google Maps search results showing the Map Pack (Local 3-Pack)
to visually demonstrate where a business ranks vs competitors.
"""

import os
import subprocess
import json
import base64
import io
import tempfile
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

from PIL import Image


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCREENSHOT_DIR = Path(__file__).parent / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)

MCP_TOOLS_PATH = Path.home() / "Documents/AI_Automation/Tools/mcp-servers"

# Crop region: search bar + Map Pack listings (left panel only).
# At 800px viewport width, Google Maps shows the list panel on the left.
# These pixel values capture the search bar at top through the 3-pack listings.
# Tweak if Google changes their layout.
CROP_BOX = (0, 0, 415, 680)  # (left, top, right, bottom)


# ---------------------------------------------------------------------------
# Screenshot Capture
# ---------------------------------------------------------------------------

def generate_maps_search_url(category: str, city: str, state: str = "Idaho") -> str:
    """
    Generate Google Maps search URL for the Map Pack.

    Args:
        category: Business category (e.g., "dog grooming")
        city: City name (e.g., "Eagle")
        state: State name (default: "Idaho")

    Returns:
        Google Maps search URL
    """
    # Format search query
    search_query = f"{category} in {city}, {state}"
    encoded_query = quote_plus(search_query)

    # Google Maps search URL
    maps_url = f"https://www.google.com/maps/search/{encoded_query}"

    return maps_url


def _crop_to_map_pack(image_data: bytes, crop_box: tuple = CROP_BOX) -> bytes:
    """Crop raw PNG bytes to just the search bar + Map Pack region."""
    img = Image.open(io.BytesIO(image_data))
    # Clamp crop box to actual image dimensions
    right = min(crop_box[2], img.width)
    bottom = min(crop_box[3], img.height)
    cropped = img.crop((crop_box[0], crop_box[1], right, bottom))
    buf = io.BytesIO()
    cropped.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def capture_map_pack_screenshot(
    business_id: str,
    category: str,
    city: str,
    state: str = "Idaho",
    viewport_width: int = 800,
    viewport_height: int = 900,
    delay_ms: int = 5000
) -> Optional[str]:
    """
    Capture a cropped screenshot of the Google Maps Map Pack (search bar + listings).

    Uses a narrow viewport so the left panel dominates, then crops to
    just the search bar and 3-pack listings for a clean, email-friendly image.
    """
    maps_url = generate_maps_search_url(category, city, state)

    screenshot_filename = f"{business_id}_map_pack.png"
    screenshot_path = SCREENSHOT_DIR / screenshot_filename

    try:
        tool_params = json.dumps({
            "url": maps_url,
            "width": viewport_width,
            "height": viewport_height
        })

        print(f"Capturing Map Pack: {maps_url}", flush=True)

        cmd = f'cd {MCP_TOOLS_PATH} && npx tsx run.ts playwright:screenshot \'{tool_params}\''

        # Write stdout to temp file to avoid pipe buffer deadlock
        # (base64 screenshots can be several MB)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp:
            tmp_path = tmp.name

        try:
            result = subprocess.run(
                f'{cmd} > {tmp_path}',
                shell=True,
                capture_output=False,
                stderr=subprocess.PIPE,
                timeout=120,
                text=True
            )

            if result.returncode != 0:
                print(f"Screenshot capture failed (exit code {result.returncode})")
                print(f"Error: {result.stderr}")
                return None

            with open(tmp_path, 'r') as f:
                stdout = f.read()
        finally:
            os.unlink(tmp_path)

        try:
            response = json.loads(stdout)

            if response.get("success") and response.get("image"):
                raw_image = base64.b64decode(response["image"])

                # Crop to just search bar + Map Pack listings
                cropped_image = _crop_to_map_pack(raw_image)

                with open(screenshot_path, "wb") as f:
                    f.write(cropped_image)

                size_kb = len(cropped_image) / 1024
                print(f"Screenshot saved: {screenshot_path} ({size_kb:.0f} KB)")
                return str(screenshot_path)
            else:
                error_msg = response.get("error", "Unknown error")
                print(f"Screenshot capture failed: {error_msg}")
                return None

        except json.JSONDecodeError as e:
            print(f"Failed to parse screenshot response: {e}")
            print(f"Raw output: {stdout[:500]}")
            return None

    except subprocess.TimeoutExpired:
        print(f"Screenshot timed out for {business_id}")
        return None
    except Exception as e:
        print(f"Error capturing screenshot: {e}")
        return None


def capture_map_pack_for_business(business_data: dict) -> Optional[str]:
    """
    Convenience function to capture Map Pack screenshot from business data.

    Args:
        business_data: Dict with keys: business_id, category, city, state (optional)

    Returns:
        Path to saved screenshot file, or None if capture failed
    """
    business_id = business_data.get('business_id') or business_data.get('place_id')
    category = business_data.get('category', 'business')
    city = business_data.get('city', 'Unknown')
    state = business_data.get('state', 'Idaho')

    if not business_id:
        print("Error: business_id or place_id required for screenshot capture")
        return None

    return capture_map_pack_screenshot(
        business_id=business_id,
        category=category,
        city=city,
        state=state
    )


# ---------------------------------------------------------------------------
# Integration with Email Generator
# ---------------------------------------------------------------------------

def get_screenshot_path(business_id: str) -> Optional[str]:
    """
    Get path to existing screenshot for a business.

    Args:
        business_id: Unique business identifier

    Returns:
        Path to screenshot file if it exists, None otherwise
    """
    screenshot_filename = f"{business_id}_map_pack.png"
    screenshot_path = SCREENSHOT_DIR / screenshot_filename

    return str(screenshot_path) if screenshot_path.exists() else None


def ensure_screenshot_exists(business_data: dict) -> Optional[str]:
    """
    Ensure screenshot exists for business, generating if needed.

    Args:
        business_data: Business data dict

    Returns:
        Path to screenshot file, or None if generation failed
    """
    business_id = business_data.get('business_id') or business_data.get('place_id')

    # Check if screenshot already exists
    existing_path = get_screenshot_path(business_id)
    if existing_path:
        return existing_path

    # Generate new screenshot
    return capture_map_pack_for_business(business_data)


# ---------------------------------------------------------------------------
# CLI Testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Test with example business
    test_business = {
        'business_id': 'test_dog_zen',
        'category': 'dog grooming',
        'city': 'Eagle',
        'state': 'Idaho'
    }

    print(f"Testing screenshot capture for: {test_business['category']} in {test_business['city']}")

    # Generate search URL
    url = generate_maps_search_url(
        test_business['category'],
        test_business['city'],
        test_business['state']
    )
    print(f"Search URL: {url}")

    # Capture screenshot
    screenshot_path = capture_map_pack_for_business(test_business)

    if screenshot_path:
        print(f"✅ Screenshot saved: {screenshot_path}")
    else:
        print("❌ Screenshot capture failed")
