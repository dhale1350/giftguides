# scripts/generate_guide.py
# Python script to generate daily blog content on a dynamic topic using Vertex AI Gemini
# and save it to a Supabase database table.

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
    from google.cloud import aiplatform
    from vertexai.generative_models import GenerativeModel, Part # Corrected import path
except ImportError as e:
    print(f"Error: Missing required Google Cloud/Vertex AI libraries. Did you install requirements.txt? {e}")
    sys.exit(1)
try:
    from supabase import create_client, Client
except ImportError as e:
    print(f"Error: Missing Supabase library. Did you install requirements.txt? {e}")
    sys.exit(1)

# --- Configuration from Environment Variables ---
try:
    SUPABASE_URL = os.environ['SUPABASE_URL'].rstrip('/')
    SUPABASE_SERVICE_KEY = os.environ['SUPABASE_SERVICE_KEY']
    GCP_PROJECT = os.environ['GCP_PROJECT']
    GCP_LOCATION = os.environ['GCP_LOCATION']
    # *** UPDATED MODEL NAME to use 'latest' tag ***
    GEMINI_MODEL_NAME = "gemini-1.5-flash-latest"
    # *** UPDATED TOPIC MODEL NAME for consistency ***
    GEMINI_TOPIC_MODEL_NAME = os.getenv('GEMINI_TOPIC_MODEL_NAME', "gemini-1.5-flash-latest")
except KeyError as e:
    print(f"Error: Environment variable {e} not set after debug checks. Check GitHub Secrets/local setup.")
    sys.exit(1)

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
        response = supabase.table('guides').insert(data_to_insert).execute()
        print(f"Guide saved successfully to Supabase. Response Data: {response.data}")
        return response.data
    except Exception as e:
        print(f"Error: Failed to save guide to Supabase: {e}")
        sys.exit(1)

# --- Gemini Interaction Functions ---
def call_gemini_api(model_name: str, prompt: str, generation_config: dict):
    """Generic function to call the Gemini API and return the text response."""
    print(f"Calling Vertex AI Gemini model: {model_name} in {GCP_LOCATION}...")
    try:
        model = GenerativeModel(model_name)
        response = model.generate_content(
            prompt,
            generation_config=generation_config,
        )
        print(f"Received response from Gemini model {model_name}.")
        if hasattr(response, 'text'):
            return response.text
        elif response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
             return "".join(part.text for part in response.candidates[0].content.parts)
        else:
            print(f"Error: Could not extract text from Gemini response for model {model_name}.")
            return None
    except Exception as e:
        print(f"Error: An exception occurred during the Vertex AI API call for model {model_name}: {e}")
        return None

def get_topic_from_gemini():
    """Asks Gemini to suggest a blog post topic."""
    print("Requesting blog topic suggestion from Gemini...")
    topic_prompt = """Suggest one interesting and specific blog post topic suitable for a general audience in the UK today.
    The topic should be engaging but not overly controversial. Output only the topic suggestion itself, without any extra text like 'Here is a topic:'."""
    topic_generation_config = { "temperature": 0.8, "max_output_tokens": 100, "top_p": 0.95, "top_k": 40 }
    topic = call_gemini_api(GEMINI_TOPIC_MODEL_NAME, topic_prompt, topic_generation_config) # Uses updated model name
    if topic:
        topic = topic.strip().strip('"').strip("'").strip()
        print(f"Suggested topic received: '{topic}'")
        return topic
    else:
        print("Warning: Failed to get topic suggestion. Using a default topic.")
        return "The Benefits of Reading Books"

def get_content_for_topic(topic: str):
    """Generates the main blog post content for the given topic."""
    print(f"Requesting blog post content for topic: '{topic}'...")
    today_str_display = datetime.date.today().strftime('%d %B %Y')
    content_prompt = f"""Please write a high-quality, engaging blog post suitable for a UK audience, approximately 800-1000 words long.
The exact title must be: "{topic}"
The output format must be **HTML only**, ready to be embedded directly into the body of a webpage's article body.
**HTML Requirements:**
* Start directly with a single `<h1>` tag containing the exact title: "{topic}".
* Structure the content logically using `<h2>` tags for main sections and `<p>` tags for paragraphs. Use standard semantic HTML.
* You may use `<strong>` or `<em>` for emphasis.
* You may include relevant, generic images using `<img>` tags with descriptive `alt` text (use placeholder image URLs like `https://placehold.co/600x400/eee/ccc?text=Relevant+Image+Placeholder`). Ensure images have `alt` attributes.
* Do NOT include `<head>`, `<body>`, or `<html>` tags.
**Content Requirements:**
* Thoroughly explore the topic: "{topic}".
* Maintain an informative, helpful, and slightly informal tone suitable for a general UK audience.
* Ensure the content is original-sounding and provides value to the reader.
* **Crucially: DO NOT include any pricing, purchasing links, affiliate links, 'buy now' buttons, or specific retailer mentions.**
* Do not include author bylines or publication dates within the HTML content itself.
Ensure the final output is well-formed, valid HTML fragment.
"""
    content_generation_config = { "temperature": 0.7, "max_output_tokens": 8192, "top_p": 0.95, "top_k": 40 }
    content_html = call_gemini_api(GEMINI_MODEL_NAME, content_prompt, content_generation_config) # Uses updated model name
    if content_html:
        return content_html
    else:
        print("Error: Failed to generate main blog content.")
        sys.exit(1)

# --- Helper Functions ---
def extract_title(html_content, default_title):
    """Extracts the content of the first H1 tag from HTML using regex."""
    try:
        match = re.search(r"<h1.*?>(.*?)<\/h1>", html_content, re.IGNORECASE | re.DOTALL)
        if match:
            title = re.sub(r'<[^>]+>', '', match.group(1))
            title = ' '.join(title.split()).strip()
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
        s = re.sub(r'[^\w\s-]', '', s)
        s = re.sub(r'[-\s]+', '-', s).strip('-')
        date_slug = datetime.date.today().strftime('%d%m%Y')
        if not s: s = "post"
        slug = f"{s}-{date_slug}"
        max_len = 100
        if len(slug) > max_len + len(date_slug) + 1:
             s_truncated = s[:max_len]
             last_hyphen = s_truncated.rfind('-')
             if last_hyphen > max_len / 2:
                 s_truncated = s_truncated[:last_hyphen]
             slug = f"{s_truncated}-{date_slug}"
        print(f"Generated slug: '{slug}'")
        return slug
    except Exception as e:
        print(f"Warning: An error occurred during slug generation: {e}")
        date_slug = datetime.date.today().strftime('%d%m%Y')
        return f"post-{date_slug}"

# --- Main Execution Logic ---
def main():
    """Main function to orchestrate the blog post generation process."""
    print(f"--- Starting Daily Blog Post Generation: {datetime.datetime.now(datetime.timezone.utc)} UTC ---")
    try:
        supabase_client: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
        print("Supabase client initialized successfully.")
    except Exception as e:
        print(f"Error initializing Supabase client: {e}")
        sys.exit(1)
    try:
         aiplatform.init(project=GCP_PROJECT, location=GCP_LOCATION)
         print("Vertex AI initialized successfully.")
    except Exception as e:
         print(f"Error initializing Vertex AI (check credentials/permissions): {e}")
         sys.exit(1)
    suggested_topic = get_topic_from_gemini()
    if not suggested_topic:
        print("Exiting due to failure in topic generation.")
        sys.exit(1)
    generated_html_content = get_content_for_topic(suggested_topic)
    extracted_title = extract_title(generated_html_content, suggested_topic)
    post_slug = generate_slug(extracted_title)
    save_guide_to_supabase(supabase_client, extracted_title, post_slug, generated_html_content)
    print(f"--- Daily Blog Post Generation Finished Successfully: {datetime.datetime.now(datetime.timezone.utc)} UTC ---")

# --- Script Entry Point ---
if __name__ == "__main__":
    main()
