# scripts/generate_guide.py
# Python script to generate daily blog content on a dynamic topic using Vertex AI Gemini
# and save it to a Supabase database table.
# Version 4: Added cleanup for markdown code fences in HTML output.

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

# --- Original Imports ---
import datetime
import re
import random
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
    GCP_LOCATION = os.environ['GCP_LOCATION'] # Recommended: us-central1 for broader model access

    # Using gemini-2.0-flash-001 as it was confirmed working
    GEMINI_MODEL_NAME = "gemini-2.0-flash-001"
    GEMINI_TOPIC_MODEL_NAME = os.getenv('GEMINI_TOPIC_MODEL_NAME', "gemini-2.0-flash-001") # Use the same model for topic generation

except KeyError as e:
    print(f"Error: Environment variable {e} not set. Check GitHub Secrets or local environment setup.")
    sys.exit(1)

# --- Supabase Interaction Function ---
def save_guide_to_supabase(supabase: Client, title: str, slug: str, content_html: str):
    """Saves the generated guide data as a new row in the Supabase 'guides' table."""
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
        # Check if the insertion was successful (Supabase API v2+ returns data on success)
        if response.data:
             print(f"Guide saved successfully to Supabase. Response Data: {response.data}")
             return response.data
        else:
             # Handle potential errors not caught by exceptions (e.g., RLS issues if key is wrong)
             print(f"Warning: Supabase insertion executed but returned no data. Check response: {response}")
             # Consider how to handle this - maybe retry or log differently
             # For now, we'll exit as it indicates a problem saving the data.
             sys.exit(1)

    except Exception as e:
        # Catch any other exceptions during the Supabase interaction
        print(f"Error: Failed to save guide to Supabase: {e}")
        # Exit the script if saving fails, as the core task cannot be completed
        sys.exit(1)

# --- Gemini Interaction Functions ---
def call_gemini_api(model_name: str, prompt: str, generation_config: dict):
    """Generic function to call the Vertex AI Gemini API and return the text response."""
    # Note: Assumes aiplatform.init() was called successfully in main()
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
        # Different response structures might exist, attempt common patterns
        if hasattr(response, 'text'):
            # Direct text attribute (common)
            return response.text
        elif response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
             # Text might be split into parts within the first candidate
             return "".join(part.text for part in response.candidates[0].content.parts)
        else:
            # Log an error if text cannot be extracted
            print(f"Error: Could not extract text from Gemini response for model {model_name}. Response: {response}")
            return None # Indicate failure

    except Exception as e:
        # Catch potential API errors (like 404 Not Found, 429 Quota Exceeded, 403 Permission Denied, etc.)
        print(f"Error: An exception occurred during the Vertex AI API call for model {model_name}: {e}")
        # Consider adding more specific error handling based on exception type if needed
        return None # Indicate failure

def get_topic_from_gemini():
    """Asks Gemini to suggest a blog post topic."""
    print("Requesting blog topic suggestion from Gemini...")
    # Define the prompt for topic generation
    topic_prompt = """Suggest one interesting and specific blog post topic suitable for a general audience in the UK today.
    The topic should be engaging but not overly controversial. Output only the topic suggestion itself, without any extra text like 'Here is a topic:'."""
    # Define generation parameters for the topic suggestion
    topic_generation_config = {
        "temperature": 0.8,         # Higher temperature for more creative/varied topics
        "max_output_tokens": 100,   # Limit the length of the topic
        "top_p": 0.95,              # Nucleus sampling
        "top_k": 40                 # Top-k sampling
    }
    # Call the Gemini API using the configured topic model
    topic = call_gemini_api(GEMINI_TOPIC_MODEL_NAME, topic_prompt, topic_generation_config)

    if topic:
        # Clean up the received topic (remove leading/trailing whitespace and quotes)
        topic = topic.strip().strip('"').strip("'").strip()
        print(f"Suggested topic received: '{topic}'")
        return topic
    else:
        # Handle failure to get a topic
        print("Warning: Failed to get topic suggestion from Gemini. Using a default topic.")
        return "The Benefits of Reading Books" # Provide a fallback topic

def clean_html_output(html_content):
    """Removes potential markdown code fences (```html ... ```) from the start/end."""
    if html_content is None:
        return None
    
    cleaned_content = html_content.strip()
    # Remove starting ```html (and variations) and ending ```
    if cleaned_content.startswith('```html') and cleaned_content.endswith('```'):
        cleaned_content = cleaned_content[len('```html'):-len('```')].strip()
        print("Cleaned ```html fences from content.")
    elif cleaned_content.startswith('```') and cleaned_content.endswith('```'):
         # Handle case where language wasn't specified in the fence
         cleaned_content = cleaned_content[len('```'):-len('```')].strip()
         print("Cleaned ``` fences from content.")
         
    return cleaned_content

def get_content_for_topic(topic: str):
    """Generates and cleans the main blog post HTML content for the given topic using Gemini."""
    print(f"Requesting blog post content for topic: '{topic}'...")
    # Get today's date for potential inclusion or context (though not used in prompt here)
    today_str_display = datetime.date.today().strftime('%d %B %Y')

    # Define the detailed prompt for generating the blog post HTML
    content_prompt = f"""Please write a high-quality, engaging blog post suitable for a UK audience, approximately 800-1000 words long.
The exact title must be: "{topic}"

The output format must be **HTML only**, ready to be embedded directly into the body of a webpage's article section.

**HTML Requirements:**
* Start directly with a single `<h1>` tag containing the exact title: "{topic}". Do not add any text before this tag.
* Structure the content logically using `<h2>` tags for main sections and `<p>` tags for paragraphs. Use standard semantic HTML.
* You may use `<strong>` or `<em>` for emphasis where appropriate.
* You may include relevant, generic images using `<img>` tags with descriptive `alt` text. Use placeholder image URLs like `https://placehold.co/600x400/eee/ccc?text=Relevant+Image+Placeholder`. Ensure all `<img>` tags have an `alt` attribute.
* Do NOT include `<head>`, `<body>`, `<html>`, `<!DOCTYPE>`, or `<style>` tags. The output must be only the HTML fragment for the article content itself.
* Ensure lists are correctly formatted using `<ul>` or `<ol>` with `<li>` tags.

**Content Requirements:**
* Thoroughly explore the topic: "{topic}".
* Maintain an informative, helpful, and slightly informal tone suitable for a general UK audience.
* Ensure the content sounds original and provides genuine value to the reader.
* **Crucially: DO NOT include any pricing, purchasing links, affiliate links, 'buy now' buttons, discount codes, or specific retailer mentions.** Focus purely on the topic information.
* Do not include author bylines, publication dates, or comment sections within the generated HTML content itself.
* Ensure the final output is a well-formed, valid HTML fragment starting with `<h1>` and containing only the blog post content.
"""
    # Define generation parameters for the main content
    content_generation_config = {
        "temperature": 0.7,         # Slightly lower temperature for more focused content
        "max_output_tokens": 8192,  # Allow for longer content (max possible for many models)
        "top_p": 0.95,              # Nucleus sampling
        "top_k": 40                 # Top-k sampling
    }
    # Call the Gemini API using the configured main content model
    raw_html_content = call_gemini_api(GEMINI_MODEL_NAME, content_prompt, content_generation_config)

    if raw_html_content:
        # *** ADDED CLEANUP STEP ***
        cleaned_html_content = clean_html_output(raw_html_content)

        # Basic validation on the *cleaned* content
        if not cleaned_html_content or not cleaned_html_content.strip().lower().startswith('<h1>'):
             print("Warning: Cleaned HTML content is empty or does not start with <h1> as expected.")
             # Fallback or exit if cleaning resulted in bad content
             # For now, we'll proceed but this might need more robust handling
        
        return cleaned_html_content # Return the cleaned HTML
    else:
        # Handle failure to generate content
        print("Error: Failed to generate main blog content from Gemini.")
        # Exit the script if content generation fails
        sys.exit(1)

# --- Helper Functions ---
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
    """Main function to orchestrate the blog post generation process."""
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
         # This uses Application Default Credentials (ADC) provided by
         # GOOGLE_APPLICATION_CREDENTIALS (local) or google-github-actions/setup-gcloud (Actions)
         aiplatform.init(project=GCP_PROJECT, location=GCP_LOCATION)
         print("Vertex AI initialized successfully.")
    except Exception as e:
         # Catch errors during Vertex AI initialization (e.g., invalid credentials, project not found)
         print(f"Error initializing Vertex AI (check credentials/permissions/project ID/location): {e}")
         sys.exit(1) # Exit if Vertex AI connection fails

    # Step 1: Get Topic Suggestion from AI
    suggested_topic = get_topic_from_gemini()
    # The get_topic_from_gemini function now returns a fallback, so no need to check for None here unless the fallback itself is problematic.

    # Step 2: Generate Main Content based on the suggested topic
    generated_html_content = get_content_for_topic(suggested_topic)
    # The get_content_for_topic function now exits on failure and includes cleanup.

    # Step 3: Process the generated content
    # Extract the title from the H1 tag (using the suggested topic as fallback)
    # Use the *cleaned* HTML content for title extraction
    extracted_title = extract_title(generated_html_content, suggested_topic)
    # Generate a URL-friendly slug from the extracted title
    post_slug = generate_slug(extracted_title)

    # Step 4: Save the processed data to Supabase
    # Pass the *cleaned* HTML content to be saved
    save_guide_to_supabase(supabase_client, extracted_title, post_slug, generated_html_content)
    # The save_guide_to_supabase function now exits on failure.

    print(f"--- Daily Blog Post Generation Finished Successfully: {datetime.datetime.now(datetime.timezone.utc)} UTC ---")

# --- Script Entry Point ---
if __name__ == "__main__":
    # Execute the main function when the script is run directly
    main()
