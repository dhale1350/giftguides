# scripts/generate_guide.py
# Python script to generate daily blog content using Vertex AI Gemini,
# automatically fetch relevant images from Pixabay,
# and save the final HTML to a Supabase database table.
# Version 11: Using re.finditer for robust placeholder replacement.

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
import requests # Added for making API calls to Pixabay
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

    # *** IMPORTANT: Add your Pixabay API Key as a GitHub Secret ***
    PIXABAY_API_KEY = os.environ['PIXABAY_API_KEY']

    # Using gemini-2.0-flash-001 as it was confirmed working
    GEMINI_MODEL_NAME = "gemini-2.0-flash-001"
    GEMINI_TOPIC_MODEL_NAME = os.getenv('GEMINI_TOPIC_MODEL_NAME', "gemini-2.0-flash-001")

except KeyError as e:
    print(f"Error: Environment variable {e} not set. Check GitHub Secrets (including PIXABAY_API_KEY) or local environment setup.")
    sys.exit(1)

# --- Supabase Interaction Function ---
def save_guide_to_supabase(supabase: Client, title: str, slug: str, content_html: str):
    """Saves the generated and image-processed guide data to Supabase."""
    print(f"Attempting to save guide '{title}' to Supabase table 'guides'...")
    try:
        # Prepare the data payload for insertion
        data_to_insert = {
            "title": title,
            "slug": slug,
            "contentHTML": content_html, # Save the HTML with real images
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
    """Generates the main blog post HTML content (with Pixabay image placeholders) for the given topic using Gemini."""
    print(f"Requesting blog post content for topic: '{topic}'...")

    # --- MODIFIED PROMPT for Pixabay ---
    # Asking Gemini to insert placeholder comments instead of <img> tags.
    content_prompt = f"""Please write a high-quality, engaging blog post suitable for a UK audience, approximately 800-1000 words long.
The exact title must be: "{topic}"

The output format must be **HTML only**, ready to be embedded directly into the body of a webpage's article section.

**HTML Requirements:**
* Start directly with a single `<h1>` tag containing the exact title: "{topic}". Do not add any text before this tag.
* Structure the content logically using `<h2>` tags for main sections and `<p>` tags for paragraphs. Use standard semantic HTML (`<strong>`, `<em>`, `<ul>`, `<ol>`, `<li>`).
* **IMPORTANT IMAGE INSTRUCTION:** Where a relevant image would enhance the content (e.g., after an introductory section or illustrating a key point), insert an HTML comment placeholder in the format: ``. For example: ``. Use 1-3 such placeholders where appropriate. Do NOT include any `<img>` tags yourself.
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
    html_with_placeholders = call_gemini_api(GEMINI_MODEL_NAME, content_prompt, content_generation_config)

    if html_with_placeholders:
        # Basic validation
        if not html_with_placeholders.strip().lower().startswith('<h1>'):
             print("Warning: Generated HTML content does not start with <h1> as expected.")
        return html_with_placeholders
    else:
        # Handle failure to generate content
        print("Error: Failed to generate main blog content from Gemini.")
        sys.exit(1)

# --- Pixabay Image Integration ---
def search_pixabay_image(query: str, api_key: str):
    """Searches Pixabay for an image based on the query and returns URL and alt text."""
    # Avoid searching if the query is empty or too short
    if not query or len(query.strip()) < 3:
        print(f"Skipping Pixabay search for empty or too short query: '{query}'")
        return None
        
    print(f"Searching Pixabay for: '{query}'")
    pixabay_api_url = "https://pixabay.com/api/"
    params = {
        "key": api_key,
        "q": query,
        "image_type": "photo", # Focus on photos
        "orientation": "horizontal", # Prefer landscape
        "safesearch": "true", # Enable safe search
        "per_page": 3 # Get a few options just in case the first isn't ideal
    }

    try:
        response = requests.get(pixabay_api_url, params=params, timeout=10) # Added timeout
        response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)

        data = response.json()

        if data and data.get("hits"):
            # Simple approach: Take the first hit
            image_data = data["hits"][0]
            image_url = image_data.get("webformatURL") # Or "largeImageURL" for higher res
            # Use Pixabay tags or the original query as alt text basis
            alt_text = image_data.get("tags", query) 

            if image_url:
                print(f"Found Pixabay image: {image_url}")
                return {
                    "url": image_url,
                    "alt": alt_text.replace('"', '&quot;') # Basic sanitization for alt attribute
                }
            else:
                 print("Warning: Found Pixabay hit but missing image URL.")
                 return None
        else:
            # Log the actual response if no hits are found for debugging
            print(f"Warning: No image results found on Pixabay for '{query}'. Response: {data}")
            return None

    except requests.exceptions.RequestException as e:
        print(f"Error calling Pixabay API: {e}")
        return None
    except Exception as e:
        print(f"Error processing Pixabay response: {e}")
        return None

# --- REVISED Placeholder Replacement Logic using finditer ---
def find_and_replace_pixabay_placeholders(html_content: str, pixabay_key: str) -> str:
    """Finds placeholders and replaces them using re.finditer."""
    if not html_content:
        return ""

    # Regex to find the placeholder comments and capture the keywords
    placeholder_pattern = r""
    
    processed_parts = [] # List to store parts of the final HTML
    last_end = 0 # Keep track of the end position of the last match
    replacements_made = 0 # Count successful replacements

    # Iterate through all non-overlapping matches found in the HTML
    for match in re.finditer(placeholder_pattern, html_content):
        start, end = match.span() # Get start and end position of the match
        keywords = match.group(1).strip() # Extract keywords from group 1

        # Append the text *before* the current match
        processed_parts.append(html_content[last_end:start])

        print(f"\nProcessing placeholder found: {match.group(0)}")
        print(f"Extracted keywords: '{keywords}'")

        # Search for image only if keywords are not empty
        if keywords:
            image_info = search_pixabay_image(keywords, pixabay_key)
            if image_info:
                # Construct the replacement HTML snippet
                replacement_html = f"""
<div class="my-6 text-center">
    <img src="{image_info['url']}" alt="{image_info['alt']}" class="max-w-full h-auto mx-auto rounded-lg shadow-md">
</div>
"""
                processed_parts.append(replacement_html) # Add the image HTML
                print(f"Replaced placeholder for '{keywords}' with Pixabay image.")
                replacements_made += 1
            else:
                # If no image found, append nothing (effectively removing the comment)
                print(f"Removing placeholder for '{keywords}' as no image was found.")
        else:
            # If keywords were empty, append nothing (remove the comment)
            print("Skipping placeholder with empty keywords.")
            
        last_end = end # Update the end position for the next iteration

    # Append any remaining text after the last match
    processed_parts.append(html_content[last_end:])

    if replacements_made == 0:
         print("No valid image placeholders found or replaced in the generated HTML.")
    else:
         print(f"Processed {replacements_made} image placeholders.")

    # Join all parts together to form the final HTML
    return "".join(processed_parts)
# --- End REVISED Placeholder Replacement Logic ---


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
    """Main function to orchestrate the blog post generation and Pixabay image processing."""
    print(f"--- Starting Daily Blog Post Generation: {datetime.datetime.now(datetime.timezone.utc)} UTC ---")

    # Initialize Supabase Client
    try:
        supabase_client: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
        print("Supabase client initialized successfully.")
    except Exception as e:
        print(f"Error initializing Supabase client: {e}")
        sys.exit(1)

    # Initialize Vertex AI Client
    try:
         # This uses Application Default Credentials (ADC)
         aiplatform.init(project=GCP_PROJECT, location=GCP_LOCATION)
         print("Vertex AI initialized successfully.")
    except Exception as e:
         # Catch errors during Vertex AI initialization
         print(f"Error initializing Vertex AI: {e}")
         sys.exit(1)

    # Step 1: Get Topic Suggestion from AI
    suggested_topic = get_topic_from_gemini()

    # Step 2: Generate Main Content (with image placeholders)
    html_with_placeholders = get_content_for_topic(suggested_topic)

    # Step 3: Clean potential markdown fences
    cleaned_html_with_placeholders = clean_html_output(html_with_placeholders)

    # --- DEBUG: Print HTML before replacement ---
    # print("\n--- HTML before image replacement ---")
    # print(cleaned_html_with_placeholders)
    # print("--- End HTML before image replacement ---\n")
    # --- End DEBUG ---

    # Step 4: Find image placeholders and replace them with Pixabay images
    final_html_content = find_and_replace_pixabay_placeholders(cleaned_html_with_placeholders, PIXABAY_API_KEY)

    # --- DEBUG: Print HTML after replacement ---
    # print("\n--- HTML after image replacement ---")
    # print(final_html_content)
    # print("--- End HTML after image replacement ---\n")
    # --- End DEBUG ---


    # Step 5: Process the final content for title and slug
    extracted_title = extract_title(final_html_content, suggested_topic)
    post_slug = generate_slug(extracted_title)

    # Step 6: Save the final data (with real images) to Supabase
    save_guide_to_supabase(supabase_client, extracted_title, post_slug, final_html_content)

    print(f"--- Daily Blog Post Generation Finished Successfully: {datetime.datetime.now(datetime.timezone.utc)} UTC ---")

# --- Script Entry Point ---
if __name__ == "__main__":
    # Execute the main function when the script is run directly
    main()
