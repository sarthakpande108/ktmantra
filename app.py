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

# Configure Gemini API
genai.configure(api_key=api_key)
model = genai.GenerativeModel("gemini-2.5-pro")

# Store active teaching sessions
sessions = {}

# ----------------- Document Extraction -----------------

def extract_text_from_pdf(path):
    try:
        text = ''
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + '\n'
        return text
    except Exception as e:
        print(f"Error extracting text from PDF: {e}")
        return None


def extract_text_from_docx(path):
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

            if file.lower().endswith('.pdf'):
                return extract_text_from_pdf(file_path)
            elif file.lower().endswith('.docx'):
                return extract_text_from_docx(file_path)

    return None


# ----------------- Text Chunking -----------------

def split_into_chunks(text, max_chars=1000):
    sentences = text.split('. ')
    chunks, current_chunk = [], ""

    for sentence in sentences:
        if len(current_chunk) + len(sentence) + 2 < max_chars:
            current_chunk += sentence + ". "
        else:
            chunks.append(current_chunk.strip())
            current_chunk = sentence + ". "

    if current_chunk:
        chunks.append(current_chunk.strip())

    return chunks


# ----------------- Routes -----------------

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/assignment')
def assignment_page():
    return render_template('assignment.html')

@app.route('/feedback')
def feedback_page():
    return render_template('feedback.html')

@app.route('/contact')
def contact_page():
    return render_template('contact.html')


@app.route('/start', methods=['POST'])
def start():
    data = request.json
    project = data.get('project', '').strip()

    if not project:
        return jsonify({'error': 'Project name is required.'}), 400

    doc_text = load_document(project)
    if not doc_text:
        return jsonify({'error': 'Project document not found.'}), 404

    chunks = split_into_chunks(doc_text)

    initial_prompt = (
        f"You are an AI assistant explaining a Knowledge Transfer document "
        f"for the '{project}' project. Explain clearly and professionally, "
        f"one section at a time. Here is the document:\n\n{doc_text}"
    )

    try:
        sessions[project] = {
            "chunks": chunks,
            "index": 0,
            "chat": model.start_chat(history=[
                {"role": "user", "parts": [initial_prompt]},
                {"role": "model", "parts": ["Understood. Starting KT session."]}
            ])
        }

        first_reply = explain_chunk(project)
        return jsonify({"message": "Session started!", "reply": first_reply})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


def explain_chunk(project):
    session = sessions.get(project)
    if not session:
        return "Session not found."

    idx = session["index"]
    chunks = session["chunks"]
    chat = session["chat"]

    if idx >= len(chunks):
        return "🎉 Completed KT! Want to revise any topic?"

    chunk = chunks[idx]
    prompt = f"Explain this in simple terms:\n\n{chunk}"

    try:
        response = chat.send_message(prompt).text
        return response + "\n\n**Did you understand this? (yes / ask question)**"
    except:
        return "Error explaining the document. Try again."


@app.route('/reply', methods=['POST'])
def reply():
    data = request.json
    project = data.get('project', '').strip()
    user_reply = data.get('user_reply', '').strip()

    session = sessions.get(project)
    if not session:
        return jsonify({"error": "Session not found!"}), 404

    chat = session["chat"]

    if any(i in user_reply.lower() for i in ["yes", "understood", "next"]):
        session["index"] += 1
        reply_message = explain_chunk(project)
    else:
        prompt = f"User asked: {user_reply}. Explain clearly again."
        reply_message = chat.send_message(prompt).text + "\n\nReady for next? (yes)"

    return jsonify({"reply": reply_message})

@app.route('/projects', methods=['GET'])
def get_projects():
    files = []
    for f in os.listdir(app.config['UPLOAD_FOLDER']):
        if f.lower().endswith(('.pdf', '.docx')):
            files.append(f)
    return jsonify({"projects": files})


if __name__ == '__main__':
    app.run(host='0.0.0.0')
