import os
import google.generativeai as genai
try:
    genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
    model = genai.GenerativeModel('gemini-2.5-flash')
    response = model.generate_content("Hello")
    print("SUCCESS: " + response.text)
except Exception as e:
    print("ERROR: " + str(e))
