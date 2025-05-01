# scripts/generate_guide.py
# Python script to generate daily blog text content using Vertex AI Gemini
# and save it to a Supabase database table.
# Version 14: More robust HTML cleanup.

# --- START DEBUGGING ---
import os
import sys
print("--- DEBUGGING START ---")
cred_path_env = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
print(f"Env Var GOOGLE_APPLICATION_CREDENTIALS = {cred_path_env}")
if cred_path_env:
    print(f"Checking if file exists at that path...")
    if os.path.exists(cred_path_env) and os.path.isfile(cred_path_env):
        print(f"SUCCESS: File found at '{cred_path_env}'")
        try:
            with open(cred_path_env, 'r') as f:
                print("File opened successfully (read permission likely ok).")
        except Exception as e:
            print(f"ERROR: File found, but cannot open/read: {e}")
            sys.exit(1)
    else:
        print(f"ERROR: File NOT found at '{cred_path_env}' according to os.path.exists()/os.path.isfile()")
        dir_path = os.path.dirname(cred_path_env)
        print(f"Checking contents of directory: '{dir_path}'")
        try:
            if os.path.isdir(dir_path):
                 print(f"Files in directory: {os.listdir(dir_path)}")
            else:
                 print(f"Directory '{dir_path}' does not exist.")
        except Exception as e:
             print(f"Could not list directory contents: {e}")
        sys.exit(1)
else:
    print("ERROR: GOOGLE_APPLICATION_CREDENTIALS environment variable is NOT SET.")
    sys.exit(1)
print("--- DEBUGGING END ---")
# --- END DEBUGGING ---

# --- Imports ---
import datetime
import re
import random
# Removed 'requests' import
try:
    # Import the necessary Google Cloud libraries for Vertex AI
    from google.cloud import aiplatform
    # Import specific classes from the Vertex AI Generative Models SDK
    from vertexai.generative_models import GenerativeModel, Part
except ImportError as e:
    print(f"Error: Missing required Google Cloud/Vertex AI libraries. Did you install requirements.txt? {e}")
    sys.exit(1)
try:
    # Import the Supabase client library
    from supabase import create_client, Client
except ImportError as e:
    print(f"Error: Missing Supabase library. Did you install requirements.txt? {e}")
    sys.exit(1)

# --- Configuration from Environment Variables ---
try:
    # Get Supabase connection details from environment variables
    SUPABASE_URL = os.environ['SUPABASE_URL'].rstrip('/')
    SUPABASE_SERVICE_KEY = os.environ['SUPABASE_SERVICE_KEY']
    # Get Google Cloud project details from environment variables
    GCP_PROJECT = os.environ['GCP_PROJECT']
    GCP_LOCATION = os.environ['GCP_LOCATION'] # e.g., us-central1

    # Using gemini-2.0-flash-001 as it was confirmed working
    GEMINI_MODEL_NAME = "gemini-2.0-flash-001"
    GEMINI_TOPIC_MODEL_NAME = os.getenv('GEMINI_TOPIC_MODEL_NAME', "gemini-2.0-flash-001")

except KeyError as e:
    # Updated error message to reflect removed API key requirement
    print(f"Error: Environment variable {e} not set. Check GitHub Secrets or local environment setup.")
    sys.exit(1)

# --- Supabase Interaction Function ---
def save_guide_to_supabase(supabase: Client, title: str, slug: str, content_html: str):
    """Saves the generated guide data (with placeholders) to Supabase."""
    print(f"Attempting to save guide '{title}' to Supabase table 'guides'...")
    try:
        # Prepare the data payload for insertion
        data_to_insert = {
            "title": title,
            "slug": slug,
            "contentHTML": content_html, # Save the cleaned HTML
            # Record the publication time in UTC ISO format
            "publishedAt": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
        # Execute the insert operation on the 'guides' table
        response = supabase.table('guides').insert(data_to_insert).execute()
        # Check if the insertion was successful
        if response.data:
             print(f"Guide saved successfully to Supabase. Response Data: {response.data}")
             return response.data
        else:
             # Handle potential errors not caught by exceptions
             print(f"Warning: Supabase insertion executed but returned no data. Check response: {response}")
             sys.exit(1)
    except Exception as e:
        # Catch any other exceptions during the Supabase interaction
        print(f"Error: Failed to save guide to Supabase: {e}")
        sys.exit(1)

# --- Gemini Interaction Functions ---
def call_gemini_api(model_name: str, prompt: str, generation_config: dict):
    """Generic function to call the Vertex AI Gemini API and return the text response."""
    print(f"Calling Vertex AI Gemini model: {model_name} in {GCP_LOCATION}...")
    try:
        # Instantiate the specific generative model
        model = GenerativeModel(model_name)
        # Send the prompt and configuration to the model
        response = model.generate_content(
            prompt,
            generation_config=generation_config,
        )
        print(f"Received response from Gemini model {model_name}.")
        # Extract the text content from the response
        if hasattr(response, 'text'):
            return response.text
        elif response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
             return "".join(part.text for part in response.candidates[0].content.parts)
        else:
            # Log an error if text cannot be extracted
            print(f"Error: Could not extract text from Gemini response for model {model_name}. Response: {response}")
            return None # Indicate failure
    except Exception as e:
        # Catch potential API errors
        print(f"Error: An exception occurred during the Vertex AI API call for model {model_name}: {e}")
        return None # Indicate failure

def get_topic_from_gemini():
    """Asks Gemini to suggest a blog post topic."""
    print("Requesting blog topic suggestion from Gemini...")
    # Define the prompt for topic generation
    topic_prompt = """Suggest one interesting and specific blog post topic suitable for a general audience in the UK today.
    The topic should be engaging but not overly controversial. Output only the topic suggestion itself, without any extra text like 'Here is a topic:'."""
    # Define generation parameters for the topic suggestion
    topic_generation_config = {
        "temperature": 0.8, "max_output_tokens": 100, "top_p": 0.95, "top_k": 40
    }
    # Call the Gemini API
    topic = call_gemini_api(GEMINI_TOPIC_MODEL_NAME, topic_prompt, topic_generation_config)
    if topic:
        # Clean up the received topic
        topic = topic.strip().strip('"').strip("'").strip()
        print(f"Suggested topic received: '{topic}'")
        return topic
    else:
        # Handle failure to get a topic
        print("Warning: Failed to get topic suggestion from Gemini. Using a default topic.")
        return "The Benefits of Reading Books" # Provide a fallback topic

# --- MORE ROBUST HTML CLEANUP ---
def clean_html_output(html_content):
    """
    Cleans the raw HTML output from Gemini.
    - Removes leading/trailing markdown code fences (```html ... ``` or ``` ... ```).
    - Removes common leading text like "Here's the HTML:".
    - Attempts to ensure the content starts with an <h1> tag.
    """
    if html_content is None:
        return None

    cleaned_content = html_content.strip()

    # 1. Remove common leading/trailing text patterns using regex (case-insensitive)
    patterns_to_remove = [
        r"^\s*```html\s*",      # Starting ```html
        r"\s*```\s*$",          # Ending ```
        r"^\s*```\s*",          # Starting ```
        r"^\s*here's the html:?\s*", # Common leading text
        r"^\s*html:\s*",            # Common leading text
    ]
    for pattern in patterns_to_remove:
        # Use re.IGNORECASE for case-insensitivity
        cleaned_content = re.sub(pattern, "", cleaned_content, flags=re.IGNORECASE | re.MULTILINE).strip()
        
    # 2. Attempt to find the first <h1> tag
    h1_match = re.search(r"<h1.*?>", cleaned_content, re.IGNORECASE)
    
    if h1_match:
        # If an <h1> tag is found, check if it's at the beginning
        if h1_match.start() > 0:
            # If there's text before the first <h1>, discard it
            print(f"Warning: Found text before the first <h1> tag. Discarding preamble.")
            cleaned_content = cleaned_content[h1_match.start():]
    else:
        # If no <h1> tag is found at all, this is unexpected based on the prompt.
        # Log a warning, but return the content as is for now.
        print("Warning: No <h1> tag found in the cleaned HTML content. Prompt instructions might not have been followed.")

    # Final strip just in case
    cleaned_content = cleaned_content.strip()

    # Optional: Add more specific cleanup rules here if needed (e.g., removing specific unwanted tags)

    # Print comparison if changes were made
    if cleaned_content != html_content.strip():
        print("Cleaned HTML content.")
    else:
        print("HTML content required no cleaning.")

    return cleaned_content
# --- END ROBUST HTML CLEANUP ---

def get_content_for_topic(topic: str):
    """Generates the main blog post HTML content (text only) for the given topic using Gemini."""
    print(f"Requesting blog post content for topic: '{topic}'...")

    # --- SIMPLIFIED PROMPT (No Images) ---
    content_prompt = f"""Please write a high-quality, engaging blog post suitable for a UK audience, approximately 800-1000 words long.
The exact title must be: "{topic}"

The output format must be **HTML only**, ready to be embedded directly into the body of a webpage's article section.

**HTML Requirements:**
* Start directly with a single `<h1>` tag containing the exact title: "{topic}". Do not add any text before this tag.
* Structure the content logically using `<h2>` tags for main sections and `<p>` tags for paragraphs. Use standard semantic HTML (`<strong>`, `<em>`, `<ul>`, `<ol>`, `<li>`).
* **IMPORTANT: Do NOT include any `<img>` tags or image placeholders.** Generate text-only content.
* Do NOT include `<head>`, `<body>`, `<html>`, `<!DOCTYPE>`, or `<style>` tags.
* Do NOT include pricing, purchasing links, affiliate links, 'buy now' buttons, discount codes, or specific retailer mentions.
* Do not include author bylines, publication dates, or comment sections within the generated HTML content itself.
* Ensure the final output is a well-formed, valid HTML fragment starting with `<h1>`.
"""
    # Define generation parameters for the main content
    content_generation_config = {
        "temperature": 0.7, "max_output_tokens": 8192, "top_p": 0.95, "top_k": 40
    }
    # Call the Gemini API
    raw_html_content = call_gemini_api(GEMINI_MODEL_NAME, content_prompt, content_generation_config)

    if raw_html_content:
        # The clean_html_output function will handle fences and ensure it starts with <h1>
        # No need for the extra check here anymore
        return raw_html_content # Return the raw content to be cleaned later
    else:
        # Handle failure to generate content
        print("Error: Failed to generate main blog content from Gemini.")
        # Exit the script if content generation fails
        sys.exit(1)

# --- Image placeholder functions removed ---

# --- Helper Functions ---
# (extract_title and generate_slug remain the same)
def extract_title(html_content, default_title):
    """Extracts the content of the first H1 tag from HTML using regex."""
    # Ensure html_content is not None before processing
    if html_content is None:
        print(f"Warning: Cannot extract title from None content. Using default: '{default_title}'")
        return default_title
        
    try:
        # Search for the first H1 tag (case-insensitive) and capture its content
        match = re.search(r"<h1.*?>(.*?)<\/h1>", html_content, re.IGNORECASE | re.DOTALL)
        if match:
            # Extract the captured group (the content inside H1)
            title = match.group(1)
            # Remove any potential leftover HTML tags inside the H1 content
            title = re.sub(r'<[^>]+>', '', title)
            # Normalize whitespace (replace multiple spaces/newlines with single space) and trim
            title = ' '.join(title.split()).strip()
            if title:
                 print(f"Extracted title: '{title}'")
                 return title
            else:
                 # Handle cases where H1 was found but was empty after cleaning
                 print("Warning: H1 tag found but content was empty after cleaning.")
        else:
            # Handle cases where no H1 tag was found at all
            print("Warning: No H1 tag found in the generated HTML content.")
    except Exception as e:
        # Catch any errors during regex processing
        print(f"Warning: An error occurred during title extraction: {e}")

    # Fallback to the default title if extraction fails or yields an empty string
    print(f"Using default title: '{default_title}'")
    return default_title

def generate_slug(title):
    """Generates a URL-friendly slug from a title string and adds the current date."""
    try:
        # Convert title to lowercase
        s = title.lower()
        # Remove characters that are not alphanumeric, whitespace, or hyphen
        s = re.sub(r'[^\w\s-]', '', s)
        # Replace whitespace and consecutive hyphens with a single hyphen
        s = re.sub(r'[-\s]+', '-', s).strip('-')
        # Get current date in ddmmyyyy format for uniqueness
        date_slug = datetime.date.today().strftime('%d%m%Y')

        # Handle empty titles after cleaning
        if not s:
            s = "post" # Default base slug if title becomes empty

        # Combine the cleaned title part and the date part
        slug = f"{s}-{date_slug}"

        # Optional: Truncate slug if it's too long (e.g., > 100 chars for the title part)
        max_len_title_part = 100
        if len(s) > max_len_title_part:
             s_truncated = s[:max_len_title_part]
             # Try to cut at the last hyphen for cleaner truncation
             last_hyphen = s_truncated.rfind('-')
             # Only cut at hyphen if it's reasonably far into the string
             if last_hyphen > max_len_title_part / 2:
                 s_truncated = s_truncated[:last_hyphen]
             slug = f"{s_truncated}-{date_slug}" # Recreate slug with truncated title part

        print(f"Generated slug: '{slug}'")
        return slug
    except Exception as e:
        # Catch any errors during slug generation
        print(f"Warning: An error occurred during slug generation: {e}")
        # Provide a very basic fallback slug in case of error
        date_slug = datetime.date.today().strftime('%d%m%Y')
        return f"post-{date_slug}"

# --- Main Execution Logic ---
def main():
    """Main function to orchestrate the blog post generation process (text only)."""
    print(f"--- Starting Daily Blog Post Generation: {datetime.datetime.now(datetime.timezone.utc)} UTC ---")

    # Initialize Supabase Client
    try:
        supabase_client: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
        print("Supabase client initialized successfully.")
    except Exception as e:
        print(f"Error initializing Supabase client: {e}")
        sys.exit(1) # Exit if Supabase connection fails

    # Initialize Vertex AI Client
    try:
         # This uses Application Default Credentials (ADC)
         aiplatform.init(project=GCP_PROJECT, location=GCP_LOCATION)
         print("Vertex AI initialized successfully.")
    except Exception as e:
         # Catch errors during Vertex AI initialization
         print(f"Error initializing Vertex AI: {e}")
         sys.exit(1) # Exit if Vertex AI connection fails

    # Step 1: Get Topic Suggestion from AI
    suggested_topic = get_topic_from_gemini()

    # Step 2: Generate Main Content (Text Only)
    generated_html_content_raw = get_content_for_topic(suggested_topic)

    # Step 3: Clean potential markdown fences and ensure starts with H1
    final_html_content = clean_html_output(generated_html_content_raw)
    
    # Ensure content is not None after cleaning before proceeding
    if final_html_content is None:
        print("Error: HTML content is None after cleaning. Exiting.")
        sys.exit(1)

    # Step 4: Process the final content for title and slug
    extracted_title = extract_title(final_html_content, suggested_topic)
    post_slug = generate_slug(extracted_title)

    # Step 5: Save the final data to Supabase
    save_guide_to_supabase(supabase_client, extracted_title, post_slug, final_html_content)

    print(f"--- Daily Blog Post Generation Finished Successfully: {datetime.datetime.now(datetime.timezone.utc)} UTC ---")

# --- Script Entry Point ---
if __name__ == "__main__":
    # Execute the main function when the script is run directly
    main()
