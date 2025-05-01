# scripts/generate_guide.py
# Python script to generate daily gift guide content using Vertex AI Gemini
# and save it to a PocketBase instance.

import os
import datetime
import re
import requests # For making HTTP requests to PocketBase
import sys # For exiting script on critical errors
import json # For handling JSON responses and errors

# --- Google Cloud / Vertex AI Libraries ---
# Ensure these are listed in requirements.txt and installed
try:
    from google.cloud import aiplatform
    from google.auth import default
    from google.auth.transport.requests import Request as GoogleAuthRequest
    # You might need specific classes depending on the Gemini API version you use
    # from google.cloud.aiplatform.gapic.prediction_service_client import PredictionServiceClient
    # from google.protobuf import json_format
    # from google.protobuf.struct_pb2 import Value
except ImportError as e:
    print(f"Error: Missing required Google Cloud libraries. Did you install requirements.txt? {e}")
    sys.exit(1)

# --- Configuration from Environment Variables ---
# Load configuration securely from environment variables set by GitHub Actions Secrets
try:
    PB_URL = os.environ['PB_URL'].rstrip('/') # Remove trailing slash if present
    PB_ADMIN_EMAIL = os.environ['PB_ADMIN_EMAIL']
    PB_ADMIN_PASSWORD = os.environ['PB_ADMIN_PASSWORD']
    GCP_PROJECT = os.environ['GCP_PROJECT']
    GCP_LOCATION = os.environ['GCP_LOCATION'] # e.g., 'us-central1', 'europe-west2'
    # --- IMPORTANT: Choose a Gemini model available in your GCP_LOCATION ---
    # Check Vertex AI documentation for available models and regions.
    # Using a newer model like 1.5 Flash is generally recommended if available.
    GEMINI_MODEL_NAME = "gemini-1.5-flash-preview-0514"
except KeyError as e:
    print(f"Error: Environment variable {e} not set. Check GitHub Secrets.")
    sys.exit(1) # Exit if essential configuration is missing

# --- PocketBase Interaction Functions ---

def get_pb_admin_token():
    """Authenticates with PocketBase using admin credentials and returns the JWT."""
    print(f"Attempting PocketBase admin authentication (URL: {PB_URL})...")
    auth_url = f"{PB_URL}/api/admins/auth-with-password"
    headers = {'Content-Type': 'application/json'}
    payload = {
        'identity': PB_ADMIN_EMAIL,
        'password': PB_ADMIN_PASSWORD
    }
    try:
        # Make the POST request to authenticate
        response = requests.post(auth_url, headers=headers, json=payload, timeout=15) # Increased timeout
        # Raise an exception if the response status code indicates an error (4xx or 5xx)
        response.raise_for_status()
        # Extract the token from the JSON response
        data = response.json()
        token = data.get('token')
        if not token:
             print("Error: Authentication successful but no token received from PocketBase.")
             sys.exit(1)
        print("PocketBase Admin Authentication Successful.")
        return token
    except requests.exceptions.Timeout:
        print(f"Error: PocketBase Admin Auth timed out after 15 seconds.")
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        # Log detailed error information
        print(f"Error: PocketBase Admin Auth Failed: {e}")
        if e.response is not None:
            print(f"Response Status Code: {e.response.status_code}")
            try:
                # Try to print JSON error details if available
                print(f"Response Body: {e.response.json()}")
            except requests.exceptions.JSONDecodeError:
                print(f"Response Body (non-JSON): {e.response.text}")
        sys.exit(1) # Exit the script if authentication fails

def save_guide_to_pb(admin_token, title, slug, content_html):
    """Saves the generated guide data as a new record in the PocketBase 'guides' collection."""
    print(f"Attempting to save guide '{title}' to PocketBase...")
    create_url = f"{PB_URL}/api/collections/guides/records"
    # Use the obtained admin token for authorization
    headers = {
        'Authorization': f'Admin {admin_token}',
        'Content-Type': 'application/json'
    }
    # Prepare the data payload according to the 'guides' collection schema
    payload = {
        "title": title,
        "slug": slug,
        "contentHTML": content_html,
        # Use UTC timestamp in ISO 8601 format, ending with 'Z' for UTC
        "publishedAt": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
    }
    try:
        # Make the POST request to create the new record
        response = requests.post(create_url, headers=headers, json=payload, timeout=20) # Increased timeout
        response.raise_for_status() # Check for HTTP errors
        created_record = response.json()
        print(f"Guide saved successfully to PocketBase. Record ID: {created_record.get('id')}")
        return created_record # Return the created record details
    except requests.exceptions.Timeout:
        print(f"Error: Save to PocketBase timed out after 20 seconds.")
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"Error: Failed to save guide to PocketBase: {e}")
        if e.response is not None:
            print(f"Response Status Code: {e.response.status_code}")
            try:
                print(f"Response Body: {e.response.json()}")
            except requests.exceptions.JSONDecodeError:
                print(f"Response Body (non-JSON): {e.response.text}")
        # Consider if retrying makes sense here, otherwise exit
        sys.exit(1)

# --- Gemini Interaction Function ---

def get_gemini_content(prompt):
    """
    Calls the Vertex AI Gemini API to generate content based on the provided prompt.

    Handles initialization and makes the API call using the google-cloud-aiplatform library.
    Ensure Application Default Credentials (ADC) are configured correctly in the environment
    (handled by google-github-actions/setup-gcloud in the workflow).
    """
    print(f"Initializing Vertex AI client for project '{GCP_PROJECT}' in location '{GCP_LOCATION}'...")
    try:
        # Initialize the Vertex AI client library. ADC will be used automatically.
        aiplatform.init(project=GCP_PROJECT, location=GCP_LOCATION)

        # Instantiate the generative model client
        # Use the specific model name configured earlier
        model = aiplatform.GenerativeModel(GEMINI_MODEL_NAME)

        print(f"Sending prompt to Gemini model '{GEMINI_MODEL_NAME}'...")

        # --- Make the API Call ---
        # Adjust generation_config parameters as needed (optional)
        generation_config = {
            "temperature": 0.7, # Controls randomness (0=deterministic, 1=max random)
            "max_output_tokens": 8192, # Max tokens for the response (check model limits)
            "top_p": 0.95, # Nucleus sampling parameter
            "top_k": 40,   # Top-k sampling parameter
        }

        # Send the prompt to the model
        # The generate_content method is suitable for multi-turn chat or single prompts
        response = model.generate_content(
            prompt,
            generation_config=generation_config,
            # safety_settings=... # Optional: configure safety filters
        )

        print("Received response from Gemini.")

        # --- Process the Response ---
        # Access the generated text content. Structure might vary slightly based on model/response type.
        # Check the `response.text` attribute for the primary generated text.
        if hasattr(response, 'text'):
            generated_text = response.text
            print("Successfully extracted text from Gemini response.")
            # print(f"--- Start Gemini Output ---\n{generated_text}\n--- End Gemini Output ---") # Optional: Log full output
            return generated_text
        elif response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
             # Fallback for potentially more complex response structures
             generated_text = "".join(part.text for part in response.candidates[0].content.parts)
             print("Successfully extracted text from Gemini response (candidate parts).")
             return generated_text
        else:
            # Log the raw response if text extraction fails
            print("Error: Could not extract text from Gemini response.")
            print(f"Full Response Object: {response}")
            sys.exit(1)

    except Exception as e:
        # Catch any exceptions during Vertex AI interaction
        print(f"Error: An exception occurred during the Vertex AI API call: {e}")
        # import traceback
        # print(traceback.format_exc()) # Uncomment for detailed traceback
        sys.exit(1)

# --- Helper Functions ---

def extract_title(html_content, default_title):
    """Extracts the content of the first H1 tag from HTML using regex."""
    try:
        # Regex: Find <h1...> tag, capture content inside (non-greedy), until </h1>
        # Case-insensitive (re.IGNORECASE), Dot matches newline (re.DOTALL)
        match = re.search(r"<h1.*?>(.*?)<\/h1>", html_content, re.IGNORECASE | re.DOTALL)
        if match:
            # Group 1 contains the content inside the tags
            title = match.group(1).strip()
            # Further cleaning: remove potential leftover HTML tags inside title, replace multiple spaces
            title = re.sub(r'<[^>]+>', '', title) # Remove inner tags
            title = ' '.join(title.split()).strip() # Normalize whitespace
            if title: # Ensure title is not empty after cleaning
                 print(f"Extracted title: '{title}'")
                 return title
            else:
                 print("Warning: H1 tag found but content was empty after cleaning.")
        else:
            print("Warning: No H1 tag found in the generated HTML content.")
    except Exception as e:
        print(f"Warning: An error occurred during title extraction: {e}")

    # Fallback to default title if extraction fails or yields empty result
    print(f"Using default title: '{default_title}'")
    return default_title

def generate_slug(title):
    """Generates a URL-friendly slug from a title string and adds the current date."""
    try:
        # 1. Convert to lowercase
        s = title.lower()
        # 2. Remove characters that are not alphanumeric, whitespace, or hyphens
        s = re.sub(r'[^\w\s-]', '', s)
        # 3. Replace sequences of whitespace and/or hyphens with a single hyphen
        s = re.sub(r'[-\s]+', '-', s)
        # 4. Remove leading or trailing hyphens that might result from the replacements
        s = s.strip('-')
        # 5. Get current date in ddmmyyyy format
        date_slug = datetime.date.today().strftime('%d%m%Y')
        # 6. Combine base slug and date slug
        # Handle empty slugs after cleaning
        if not s:
            s = "guide"
        slug = f"{s}-{date_slug}"
        print(f"Generated slug: '{slug}'")
        return slug
    except Exception as e:
        print(f"Warning: An error occurred during slug generation: {e}")
        # Provide a simple fallback slug in case of error
        date_slug = datetime.date.today().strftime('%d%m%Y')
        return f"guide-{date_slug}"

# --- Main Execution Logic ---

def main():
    """Main function to orchestrate the guide generation process."""
    print(f"--- Starting Daily Guide Generation: {datetime.datetime.now(datetime.timezone.utc)} UTC ---")

    # 1. Authenticate with PocketBase
    pb_admin_token = get_pb_admin_token()

    # 2. Prepare the prompt for Gemini
    # Use today's date, formatted for UK locale display in the title
    today_str_display = datetime.date.today().strftime('%d %B %Y') # e.g., 01 May 2025
    today_str_prompt = datetime.date.today().strftime('%d/%m/%Y') # Format for the prompt text

    # Construct the detailed prompt for the AI model
    prompt = f"""Please write a high-quality, engaging blog post suitable for a UK audience, approximately 1000 words long.

The exact title must be: "Top 10 Home Office Gadgets for {today_str_display}"

The output format must be **HTML only**, ready to be embedded directly into the body of a webpage.

**HTML Requirements:**
* Start directly with a single `<h1>` tag containing the exact title specified above.
* Use `<h2>` tags for each of the 10 gadget subheadings (e.g., `<h2>1. Gadget Name</h2>`, `<h2>2. Another Gadget</h2>`, etc.).
* Use `<p>` tags for descriptive paragraphs below each `<h2>`.
* You may use `<strong>` or `<em>` for emphasis where appropriate.
* You may include relevant, generic images using `<img>` tags with descriptive `alt` text (use placeholder image URLs like `https://placehold.co/600x400/eee/ccc?text=Gadget+Image+Placeholder` if actual images aren't possible). Ensure images have `alt` attributes.

**Content Requirements:**
* Focus on describing 10 distinct home office gadgets.
* Explain the features and benefits of each gadget specifically for someone working from home in the UK.
* Maintain an informative, helpful, and slightly informal tone.
* **Crucially: DO NOT include any pricing, purchasing links, affiliate links, 'buy now' buttons, or specific retailer mentions.** The focus is purely on the gadgets themselves.
* Do not include any introductory or concluding text outside of the H1 title and the 10 gadget sections.

Ensure the final output is well-formed, valid HTML.
"""
    # print(f"Generated Prompt:\n---\n{prompt}\n---") # Optional: Log the prompt

    # 3. Call Gemini to get the HTML content
    generated_html_content = get_gemini_content(prompt)

    # 4. Process the generated content
    default_title = f"Home Office Gift Guide for {today_str_display}"
    extracted_title = extract_title(generated_html_content, default_title)
    guide_slug = generate_slug(extracted_title)

    # 5. Save the processed data to PocketBase
    save_guide_to_pb(pb_admin_token, extracted_title, guide_slug, generated_html_content)

    print(f"--- Daily Guide Generation Finished Successfully: {datetime.datetime.now(datetime.timezone.utc)} UTC ---")

# --- Script Entry Point ---
if __name__ == "__main__":
    # This block executes only when the script is run directly (not imported as a module)
    main()