# scripts/generate_guide.py
# Python script to generate daily gift guide content using Vertex AI Gemini
# and save it to a Supabase database table.

import os
import datetime
import re
import requests # For making HTTP requests to PocketBase (if needed, not currently used)
import sys # For exiting script on critical errors

# --- Google Cloud / Vertex AI Libraries ---
try:
    from google.cloud import aiplatform
    # from google.auth import default # ADC is handled by library/action
    # from google.auth.transport.requests import Request as GoogleAuthRequest
except ImportError as e:
    print(f"Error: Missing required Google Cloud libraries. Did you install requirements.txt? {e}")
    sys.exit(1)

# --- Supabase Client Library ---
try:
    from supabase import create_client, Client
except ImportError as e:
    print(f"Error: Missing Supabase library. Did you install requirements.txt? {e}")
    sys.exit(1)

# --- Configuration from Environment Variables ---
try:
    # Supabase Credentials
    SUPABASE_URL = os.environ['SUPABASE_URL']
    SUPABASE_SERVICE_KEY = os.environ['SUPABASE_SERVICE_KEY'] # Service Role Key

    # Google Cloud Credentials
    GCP_PROJECT = os.environ['GCP_PROJECT']
    GCP_LOCATION = os.environ['GCP_LOCATION'] # e.g., 'europe-west2'
    # Ensure this model is available in GCP_LOCATION
    GEMINI_MODEL_NAME = "gemini-1.5-flash-preview-0514"

except KeyError as e:
    print(f"Error: Environment variable {e} not set. Check GitHub Secrets.")
    sys.exit(1) # Exit if essential configuration is missing

# --- Supabase Interaction Function ---

def save_guide_to_supabase(supabase: Client, title: str, slug: str, content_html: str):
    """Saves the generated guide data as a new row in the Supabase 'guides' table."""
    print(f"Attempting to save guide '{title}' to Supabase table 'guides'...")
    try:
        data_to_insert = {
            "title": title,
            "slug": slug,
            "contentHTML": content_html,
            "publishedAt": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
        # Use the Supabase client to insert data
        response = supabase.table('guides').insert(data_to_insert).execute()

        # Basic check: If execute() didn't raise an exception, assume success for now.
        # More robust checking might inspect response.data or potential error attributes.
        print(f"Guide saved successfully to Supabase. Response Data: {response.data}")
        return response.data

    except Exception as e:
        print(f"Error: Failed to save guide to Supabase: {e}")
        # Consider logging more details if available from the exception object
        sys.exit(1) # Exit script on failure

# --- Gemini Interaction Function ---

def get_gemini_content(prompt):
    """
    Calls the Vertex AI Gemini API to generate content based on the provided prompt.
    Uses the google-cloud-aiplatform library and relies on Application Default Credentials (ADC)
    being set up by the GitHub Action (google-github-actions/setup-gcloud).
    """
    print(f"Initializing Vertex AI client for project '{GCP_PROJECT}' in location '{GCP_LOCATION}'...")
    try:
        # Initialize the Vertex AI client library. ADC should be picked up automatically.
        aiplatform.init(project=GCP_PROJECT, location=GCP_LOCATION)

        # Instantiate the generative model client using the specified model name
        model = aiplatform.GenerativeModel(GEMINI_MODEL_NAME)

        print(f"Sending prompt to Gemini model '{GEMINI_MODEL_NAME}'...")

        # --- Make the API Call ---
        # Configure generation parameters (optional, defaults are often reasonable)
        generation_config = {
            "temperature": 0.75, # Slightly higher temperature for more creative gift ideas
            "max_output_tokens": 8192, # Ensure enough tokens for a ~1000 word HTML post
            "top_p": 0.95,
            "top_k": 40,
        }

        # Send the prompt to the model using the generate_content method
        # This method is suitable for single-turn text generation.
        response = model.generate_content(
            prompt,
            generation_config=generation_config,
            # stream=False # Set to True if you wanted to process chunks as they arrive
        )

        print("Received response from Gemini.")

        # --- Process the Response ---
        # Access the generated text content.
        # For simple text generation, response.text is usually the primary attribute.
        if hasattr(response, 'text'):
            generated_text = response.text
            print("Successfully extracted text from Gemini response.")
            # Optional: Log a snippet for verification, not the whole potentially large HTML
            # print(f"--- Start Gemini Output Snippet ---\n{generated_text[:200]}...\n--- End Gemini Output Snippet ---")
            return generated_text
        elif response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
             # Fallback for potentially more complex response structures if .text isn't populated
             generated_text = "".join(part.text for part in response.candidates[0].content.parts)
             print("Successfully extracted text from Gemini response (candidate parts).")
             return generated_text
        else:
            # Log the raw response if text extraction fails
            print("Error: Could not extract text from Gemini response. Structure might be unexpected.")
            # Be cautious logging the full response if it might contain sensitive info or be huge
            # Consider logging specific parts or metadata for debugging.
            # print(f"Full Response Object (Metadata): {response}") # Example: Log metadata
            sys.exit(1)

    except Exception as e:
        # Catch any exceptions during Vertex AI initialization or API call
        print(f"Error: An exception occurred during the Vertex AI API call: {e}")
        # import traceback
        # print(traceback.format_exc()) # Uncomment for detailed traceback during debugging
        sys.exit(1)


# --- Helper Functions (Same as before) ---

def extract_title(html_content, default_title):
    """Extracts the content of the first H1 tag from HTML using regex."""
    try:
        match = re.search(r"<h1.*?>(.*?)<\/h1>", html_content, re.IGNORECASE | re.DOTALL)
        if match:
            title = re.sub(r'<[^>]+>', '', match.group(1)) # Remove inner tags
            title = ' '.join(title.split()).strip() # Normalize whitespace
            if title:
                 print(f"Extracted title: '{title}'")
                 return title
            else:
                 print("Warning: H1 tag found but content was empty after cleaning.")
        else:
            print("Warning: No H1 tag found in the generated HTML content.")
    except Exception as e:
        print(f"Warning: An error occurred during title extraction: {e}")
    print(f"Using default title: '{default_title}'")
    return default_title

def generate_slug(title):
    """Generates a URL-friendly slug from a title string and adds the current date."""
    try:
        s = title.lower()
        s = re.sub(r'[^\w\s-]', '', s) # Keep word chars, whitespace, hyphens
        s = re.sub(r'[-\s]+', '-', s).strip('-') # Replace whitespace/multi-hyphens with single hyphen
        date_slug = datetime.date.today().strftime('%d%m%Y')
        if not s: s = "guide" # Handle empty title after cleaning
        slug = f"{s}-{date_slug}"
        print(f"Generated slug: '{slug}'")
        return slug
    except Exception as e:
        print(f"Warning: An error occurred during slug generation: {e}")
        date_slug = datetime.date.today().strftime('%d%m%Y')
        return f"guide-{date_slug}" # Fallback slug

# --- Main Execution Logic ---

def main():
    """Main function to orchestrate the guide generation process."""
    print(f"--- Starting Daily Guide Generation: {datetime.datetime.now(datetime.timezone.utc)} UTC ---")

    # 1. Initialize Supabase Client
    try:
        supabase_client: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
        print("Supabase client initialized successfully.")
    except Exception as e:
        print(f"Error initializing Supabase client: {e}")
        sys.exit(1)

    # 2. Prepare the prompt for Gemini
    today_str_display = datetime.date.today().strftime('%d %B %Y') # e.g., 01 May 2025
    # Construct the detailed prompt for the AI model
    prompt = f"""Please write a high-quality, engaging blog post suitable for a UK audience, approximately 1000 words long.

The exact title must be: "Top 10 Home Office Gadgets for {today_str_display}"

The output format must be **HTML only**, ready to be embedded directly into the body of a webpage's article body.

**HTML Requirements:**
* Start directly with a single `<h1>` tag containing the exact title specified above.
* Use `<h2>` tags for each of the 10 gadget subheadings (e.g., `<h2>1. Gadget Name</h2>`, `<h2>2. Another Gadget</h2>`, etc.).
* Use `<p>` tags for descriptive paragraphs below each `<h2>`. You may use `<strong>` or `<em>` for emphasis where appropriate.
* You may include relevant, generic images using `<img>` tags with descriptive `alt` text (use placeholder image URLs like `https://placehold.co/600x400/eee/ccc?text=Gadget+Image+Placeholder` if actual images aren't possible). Ensure images have `alt` attributes and are relevant to the gadget.
* Use standard, semantic HTML. Do not include `<head>`, `<body>`, or `<html>` tags.

**Content Requirements:**
* Focus on describing 10 distinct home office gadgets available or relevant in the UK market.
* Explain the features and benefits of each gadget specifically for someone working from home in the UK.
* Maintain an informative, helpful, and slightly informal tone.
* **Crucially: DO NOT include any pricing, purchasing links, affiliate links, 'buy now' buttons, or specific retailer mentions.** The focus is purely on the gadgets themselves.
* Do not include any introductory text before the H1 or concluding text after the 10th gadget description.

Ensure the final output is well-formed, valid HTML fragment.
"""

    # 3. Call Gemini to get the HTML content
    generated_html_content = get_gemini_content(prompt)

    # 4. Process the generated content
    default_title = f"Home Office Gift Guide for {today_str_display}"
    extracted_title = extract_title(generated_html_content, default_title)
    guide_slug = generate_slug(extracted_title)

    # 5. Save the processed data to Supabase
    save_guide_to_supabase(supabase_client, extracted_title, guide_slug, generated_html_content)

    print(f"--- Daily Guide Generation Finished Successfully: {datetime.datetime.now(datetime.timezone.utc)} UTC ---")

# --- Script Entry Point ---
if __name__ == "__main__":
    main()
