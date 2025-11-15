from flask import Flask, render_template, request, jsonify
import os
import pdfplumber
import docx
import google.generativeai as genai
import dotenv

dotenv.load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")

# Initialize Flask application
app = Flask(__name__)

# Ensure the documents directory exists
app.config['UPLOAD_FOLDER'] = 'documents'
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# Configure Gemini with a placeholder API key
genai.configure(api_key=api_key )
model = genai.GenerativeModel("gemini-2.5-flash")

# In-memory teaching sessions: project -> session state
# A dictionary to store active chat sessions, not suitable for production.
sessions = {}

def extract_text_from_pdf(path):
    """Extracts text from a PDF file."""
    try:
        text = ''
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                text += page.extract_text() + '\n'
        return text
    except Exception as e:
        print(f"Error extracting text from PDF: {e}")
        return None

def extract_text_from_docx(path):
    """Extracts text from a DOCX file."""
    try:
        doc = docx.Document(path)
        return '\n'.join([p.text for p in doc.paragraphs])
    except Exception as e:
        print(f"Error extracting text from DOCX: {e}")
        return None

def load_document(project_name):
    """Finds and extracts text from a document matching the project name."""
    for file in os.listdir(app.config['UPLOAD_FOLDER']):
        if project_name.lower() in file.lower():
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], file)
            if file.endswith('.pdf'):
                return extract_text_from_pdf(file_path)
            elif file.endswith('.docx'):
                return extract_text_from_docx(file_path)
    return None

def split_into_chunks(text, max_chars=1000):
    """
    Splits text into chunks of a maximum character length.
    This helps the model process large documents more effectively.
    """
    sentences = text.split('. ')
    chunks = []
    current_chunk = ""

    for sentence in sentences:
        if len(current_chunk) + len(sentence) + 2 < max_chars:
            current_chunk += sentence + ". "
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = sentence + ". "
    if current_chunk:
        chunks.append(current_chunk.strip())
    
    return chunks

@app.route('/')
def index():
    """Renders the main HTML page for the chatbot."""
    return render_template('index.html')

# Route for the Learning/Assignment page
@app.route('/assignment')
def assignment_page():
    """Renders the assignment.html page."""
    return render_template('assignment.html')


@app.route('/feedback')
def feedback_page():
    """Renders the feedback.html page."""
    return render_template('feedback.html')

@app.route('/contact')
def contact_page():
    """Renders the contact.html page."""
    return render_template('contact.html')



@app.route('/start', methods=['POST'])
def start():
    """Initializes a new teaching session for a given project."""
    data = request.json
    project = data.get('project', '').strip()
    
    if not project:
        return jsonify({'error': 'Project name is required.'}), 400

    doc_text = load_document(project)
    if not doc_text:
        return jsonify({'error': 'Project document not found. Please check the file name and try again.'}), 404

    chunks = split_into_chunks(doc_text)
    
    # Initialize a new chat session for this project
    # The initial prompt sets the context for the entire conversation.
    initial_prompt = (
        f"You are an AI assistant tasked with explaining a Knowledge Transfer "
        f"document for the '{project}' project to a new employee. "
        f"Your goal is to explain the document in simple and professional way,also dont give entier detials at once only give client name,its background and company contract with that client in which feild and from how many years"
        f"one section at a time. The document text is:\n\n{doc_text}"
    )
    
    try:
        sessions[project] = {
            "chunks": chunks,
            "index": 0,
            "chat": model.start_chat(history=[{
                "role": "user",
                "parts": [initial_prompt]
            }, {
                "role": "model",
                "parts": ["Understood. I'm ready to begin the KT session."]
            }])
        }
        reply_message = explain_chunk(project)
        return jsonify({"message": "Teaching session started!", "reply": reply_message})
    except Exception as e:
        return jsonify({'error': f"An error occurred while starting the session: {str(e)}"}), 500

def explain_chunk(project):
    """A helper function to get the next chunk's explanation."""
    session = sessions.get(project)
    if not session:
        return "Session not found. Please start a new session."

    index = session["index"]
    if index >= len(session["chunks"]):
        return "✅ You've completed the KT session! Let me know if you want to review anything."

    chunk = session["chunks"][index]
    chat = session["chat"]

    try:
        # Prompt the model to explain the current chunk
        prompt = f"Explain this part of the document in simple terms:\n\n{chunk}"
        reply = chat.send_message(prompt).text
        return reply + "\n\n**Did you understand this part?** (You can say 'yes' or ask a question.)"
    except Exception as e:
        print(f"Error sending message to Gemini: {e}")
        return "I'm sorry, I ran into a problem while processing that chunk. Let's try again."

@app.route('/reply', methods=['POST'])
def reply():
    """Handles the user's reply to the teaching session."""
    data = request.json
    project = data.get('project', '').strip()
    user_reply = data.get('user_reply', '').strip()

    session = sessions.get(project)
    if not session:
        return jsonify({"error": "Session not found. Please start a new session."}), 404

    chat = session["chat"]
    
    # Check for "yes" or similar keywords to move to the next chunk
    if "yes" in user_reply.lower() or "understood" in user_reply.lower() or "next" in user_reply.lower():
        session["index"] += 1
        reply_message = explain_chunk(project)
    else:
        # User is asking a clarifying question
        try:
            prompt = f"The user asked: '{user_reply}'. Please clarify or explain it again, considering the previous explanation and the document."
            response = chat.send_message(prompt).text
            reply_message = response + "\n\n**Ready to move on?**"
        except Exception as e:
            print(f"Error sending clarification message to Gemini: {e}")
            reply_message = "I'm sorry, I couldn't process your clarification request. Please try again."

    return jsonify({"reply": reply_message})

if __name__ == '__main__':
    app.run(debug=True)
